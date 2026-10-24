"""Human-written controls: ingestion with provenance, sampling and validation (plan.md section 5).

    .venv\\Scripts\\python training\\generation_eval\\human.py ingest SOURCE FILE    # -> data/generation_eval/human/SOURCE.jsonl
    .venv\\Scripts\\python training\\generation_eval\\human.py summary

A source is ingested only after a person sets its license_status to "confirmed" in sources.json.
Every essay gets: human_id, source, source_id, tier, license, permitted_use, provenance_method,
collected, genre, topic, grade/ELL where the source gives them, words, edit_history and ai_assistance
("unknown" unless the source documents them; never assumed), split, text. Essays under 150 words or
with malformed text are kept out with a recorded reason. Splits: PERSUADE follows the prompt split
(prompts.py persuade); other sources are split by a hash of their id, then a seeded sample is drawn
per split. Exclusions and the draw are written beside the data.
"""
import csv
import json
import random
import re
import sys

from common import HUMAN, HERE, LOCAL, read_jsonl, sha256_file, sha256_text, words, write_jsonl

MIN_WORDS = 150
SEED = 20261024
SOURCES = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))["sources"]


def malformed(text):
    """Reasons a text can't be used as an essay (empty, mostly non-letters, or encoding damage)."""
    if not text or not text.strip():
        return "empty"
    visible = re.sub(r"\s", "", text)   # spacing isn't content: some source essays carry long runs of spaces
    if sum(ch.isalpha() for ch in visible) / max(1, len(visible)) < 0.6:
        return "mostly non-letter characters"
    if "�" in text or re.search(r"Ã.|â€", text):
        return "encoding damage"
    return None


def read_persuade(path):
    """One essay per essay_id_comp (the CSV has a row per annotated element; essay_id was mangled into
    scientific notation and isn't unique)."""
    csv.field_size_limit(1 << 30)
    seen = set()
    for r in csv.DictReader(open(path, encoding="utf-8", newline="")):
        if r["essay_id_comp"] in seen:
            continue
        seen.add(r["essay_id_comp"])
        yield {"source_id": r["essay_id_comp"], "text": r["full_text"], "topic": r["prompt_name"],
               "genre": f"argumentative ({r['task'].lower()})", "grade": r["grade_level"] or None,
               "ell": (r["ell_status"].strip() or None), "prompt_name": r["prompt_name"], "provider": r["provider"]}


def read_ellipse(path):
    # ELLIPSE_Final_github_train.csv: one row per essay; all independent, timed state-test essays by ELLs.
    for r in csv.DictReader(open(path, encoding="utf-8", newline="")):
        yield {"source_id": r["text_id_kaggle"], "text": r["full_text"], "topic": r["prompt"],
               "genre": f"argumentative ({r['task'].lower()}, timed state test)", "grade": r["grade"], "ell": "yes"}


def read_jsonl_source(path):
    for r in read_jsonl(path):
        yield {"source_id": r["id"], "text": r["text"], "topic": r.get("topic", ""), "genre": r.get("genre", ""),
               "grade": r.get("grade"), "ell": r.get("ell"), "student": r.get("student")}


ADAPTERS = {"persuade": read_persuade, "ellipse": read_ellipse, "jsonl": read_jsonl_source}


def persuade_ids():
    """Every PERSUADE essay id. ELLIPSE and PERSUADE share Kaggle ids, and 449 ELLIPSE essays are also in
    PERSUADE (436 word for word), so ELLIPSE essays found there are excluded and the sources stay disjoint."""
    path = next((LOCAL / "sources" / "persuade").glob("*.csv"), None)
    if not path:
        raise SystemExit("Ingesting ELLIPSE needs the PERSUADE CSV, to exclude the essays the two corpora share.")
    return {r["source_id"] for r in read_persuade(path)}


def persuade_splits():
    folder = LOCAL / "prompts"
    out = {}
    for split in ("dev", "eval"):
        path = folder / f"persuade-{split}.jsonl"
        if not path.exists():
            raise SystemExit("Build the PERSUADE prompts first (prompts.py persuade); the human split follows them.")
        out.update({p["topic"]: split for p in read_jsonl(path)})
    return out


def ingest(name, path):
    src = SOURCES[name]
    if src["license_status"] != "confirmed":
        raise SystemExit(f"{name}: license_status is {src['license_status']!r}. Read the source's terms and record "
                         "them in sources.json before ingesting.")
    rows, excluded = [], []
    shared = persuade_ids() if name == "ellipse" else set()
    for r in ADAPTERS[src["adapter"]](path):
        reason = ("also in PERSUADE (same Kaggle id)" if r["source_id"] in shared else None) \
            or malformed(r["text"]) or (f"under {MIN_WORDS} words" if words(r["text"]) < MIN_WORDS else None)
        if reason:
            excluded.append({"source_id": r["source_id"], "reason": reason})
            continue
        rows.append(r)
    rng = random.Random(SEED)
    chosen = []
    if name == "persuade":
        split_of = persuade_splits()
        by_prompt = {}
        for r in rows:
            if r["prompt_name"] in split_of:
                by_prompt.setdefault(r["prompt_name"], []).append(r)
        for prompt in sorted(by_prompt):
            split = split_of[prompt]
            group = sorted(by_prompt[prompt], key=lambda r: r["source_id"])
            take = rng.sample(group, min(src["per_prompt"][split], len(group)))
            chosen += [{**r, "split": split} for r in take]
    else:
        for split in ("dev", "eval"):
            pool = sorted((r for r in rows if (int(sha256_text(f"{name}:{r['source_id']}")[:8], 16) % 4 == 0)
                           == (split == "dev")), key=lambda r: r["source_id"])
            take = rng.sample(pool, min(src["sample"][split], len(pool)))
            chosen += [{**r, "split": split} for r in take]
    out = [{"human_id": f"h-{name}-{r['source_id']}", "source": name, "source_id": r["source_id"], "tier": src["tier"],
            "license": src["license"], "permitted_use": src["permitted_use"], "provenance_method": src["provenance_method"],
            "collected": src["collected"], "genre": r["genre"], "topic": r["topic"], "grade": r.get("grade"),
            "ell": r.get("ell"), "provider": r.get("provider"),
            "words": words(r["text"]), "edit_history": "unknown", "ai_assistance": "unknown",
            "split": r["split"], "text": r["text"].strip()} for r in chosen]
    write_jsonl(HUMAN / f"{name}.jsonl", out)
    (HUMAN / f"{name}-ingest.json").write_text(json.dumps({
        "source_file_sha256": sha256_file(path), "read": len(rows) + len(excluded), "excluded": excluded,
        "chosen": {s: sum(1 for r in out if r["split"] == s) for s in ("dev", "eval")}, "seed": SEED,
        "output_sha256": sha256_file(HUMAN / f"{name}.jsonl")}, indent=1), encoding="utf-8")
    print(f"{name}: {len(out)} essays chosen ({len(excluded)} excluded with reasons)")


def load(split=None, tiers=("A", "B")):
    rows = []
    for name in SOURCES:
        path = HUMAN / f"{name}.jsonl"
        if path.exists():
            rows += [r for r in read_jsonl(path) if r["tier"] in tiers and (split is None or r["split"] == split)]
    return rows


def summary():
    for name, src in SOURCES.items():
        path = HUMAN / f"{name}.jsonl"
        state = f"{len(read_jsonl(path))} essays" if path.exists() else "not ingested"
        print(f"  {name} (tier {src['tier']}): license {src['license_status']}; {state}")


if __name__ == "__main__":
    if sys.argv[1] == "ingest":
        ingest(sys.argv[2], sys.argv[3])
    else:
        summary()
