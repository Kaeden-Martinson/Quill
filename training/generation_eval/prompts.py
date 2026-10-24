"""Builds the prompt inventory and its dev / eval split (plan.md section 4).

    .venv\\Scripts\\python training\\generation_eval\\prompts.py build      # Quill-genre family
    .venv\\Scripts\\python training\\generation_eval\\prompts.py persuade   # once PERSUADE 2.0 is downloaded
    .venv\\Scripts\\python training\\generation_eval\\prompts.py check      # verify the lock

Quill-genre family: the 16 assignments that chose the live drafting prompt (writing_eval/
assignments.jsonl) are dev only. New prompts come from topics.json, written before any generation:
two whole genres are drawn as held out (eval only), then the remaining topics are shuffled into 14 eval,
12 dev and the rest reserve. Lengths cycle short / medium / long over each split in a seeded order.
Every draw uses a fixed seed, so rerunning gives the same inventory.

PERSUADE family: the corpus's own prompts, split 7 dev / 8 eval by a seeded shuffle of the sorted
prompt names; written to data/generation_eval/prompts (local, since it quotes the corpus).

Each prompt records: id, family, genre, goal, audience, topic, length, instructions, evidence,
constraints, split. prompts/lock.json holds each file's sha256; check() fails if a file changed.
"""
import csv
import json
import random
import sys

from common import LOCAL, PROMPTS, ROOT, read_jsonl, sha256_file, write_jsonl

SEED = 20261023
LENGTHS = ("short", "medium", "long")
HELD_OUT_GENRES = 2
EVAL_NEW, DEV_NEW = 14, 12
VOICE = "none"   # a new writer with no samples: the app sends "Not given." (editor.draft_prompt)
CONSTRAINTS = "no voice samples; tone not set; Quill's default drafting settings"


def with_lengths(rows, rng):
    order = list(range(len(rows)))
    rng.shuffle(order)
    for k, i in enumerate(order):
        rows[i]["length"] = LENGTHS[k % 3]
    return rows


def build():
    rng = random.Random(SEED)
    pool = json.loads((PROMPTS.parent / "topics.json").read_text(encoding="utf-8"))["genres"]
    genres = sorted(pool)
    held_out = sorted(rng.sample(genres, HELD_OUT_GENRES))
    entries = []
    for g in genres:
        for n, t in enumerate(pool[g]["topics"], 1):
            entries.append({"id": f"q-{g}-{n}", "family": "quill-genre", "genre": g, "goal": pool[g]["goal"],
                            "audience": t["audience"], "topic": t["topic"], "instructions": t["instructions"],
                            "evidence": pool[g]["evidence"], "constraints": CONSTRAINTS, "voice": VOICE})
    held = [e for e in entries if e["genre"] in held_out]
    rest = [e for e in entries if e["genre"] not in held_out]
    rng.shuffle(rest)
    eval_rows = held + rest[:EVAL_NEW]
    dev_rows = rest[EVAL_NEW:EVAL_NEW + DEV_NEW]
    reserve = rest[EVAL_NEW + DEV_NEW:]
    for split, rows in (("eval", eval_rows), ("dev", dev_rows), ("reserve", reserve)):
        for r in rows:
            r["split"] = split
            r["held_out_genre"] = r["genre"] in held_out
        with_lengths(rows, rng)
    existing = []
    for a in read_jsonl(ROOT / "training" / "writing_eval" / "assignments.jsonl"):
        existing.append({"id": f"a-{a['id']}", "family": "quill-existing", "genre": "mixed (assignment set)",
                         "goal": a["goal"], "audience": a["audience"], "topic": a["id"],
                         "instructions": a["instructions"], "evidence": "the writer's points",
                         "constraints": CONSTRAINTS + "; used to choose the live prompt, so dev only",
                         "voice": VOICE, "length": "medium", "split": "dev", "held_out_genre": False})
    files = {"quill-dev.jsonl": existing + sorted(dev_rows, key=lambda r: r["id"]),
             "quill-eval.jsonl": sorted(eval_rows, key=lambda r: r["id"]),
             "quill-reserve.jsonl": sorted(reserve, key=lambda r: r["id"])}
    for name, rows in files.items():
        write_jsonl(PROMPTS / name, rows)
    lock = {"seed": SEED, "held_out_genres": held_out,
            "files": {f"training/generation_eval/prompts/{n}": sha256_file(PROMPTS / n) for n in files}}
    (PROMPTS / "lock.json").write_text(json.dumps(lock, indent=1), encoding="utf-8")
    print(f"held-out genres {held_out}; dev {len(files['quill-dev.jsonl'])} "
          f"(16 existing + {len(dev_rows)} new), eval {len(eval_rows)}, reserve {len(reserve)}")


PERSUADE_COLUMNS = ("prompt_name", "task", "assignment", "source_text", "grade_level", "essay_word_count")


def persuade(csv_path=None):
    """Prompts from PERSUADE 2.0's own CSV. Column names are checked rather than assumed."""
    csv_path = csv_path or next((LOCAL / "sources" / "persuade").glob("*.csv"), None)
    if not csv_path:
        raise SystemExit("PERSUADE 2.0 isn't downloaded (data/generation_eval/sources/persuade/*.csv).")
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8", newline="")))
    missing = [c for c in PERSUADE_COLUMNS if c not in rows[0]]
    if missing:
        raise SystemExit(f"{csv_path} lacks expected columns {missing}; adapt PERSUADE_COLUMNS after reading its docs.")
    by_prompt = {}
    for r in rows:
        by_prompt.setdefault(r["prompt_name"], []).append(r)
    names = sorted(by_prompt)
    rng = random.Random(SEED + 1)
    rng.shuffle(names)
    eval_names = set(names[:8])
    out = {"dev": [], "eval": []}
    for name in sorted(by_prompt):
        group = by_prompt[name]
        first = group[0]
        counts = sorted(int(r["essay_word_count"]) for r in group if r["essay_word_count"].isdigit())
        median = counts[len(counts) // 2] if counts else None
        length = "short" if median and median < 375 else "medium" if not median or median < 700 else "long"
        grades = sorted({r["grade_level"] for r in group if r["grade_level"]})
        split = "eval" if name in eval_names else "dev"
        instructions = first["assignment"].strip()
        if first["source_text"].strip():
            instructions += "\n\nSource text:\n" + first["source_text"].strip()
        out[split].append({"id": "p-" + "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-"),
                           "family": "persuade", "genre": f"argumentative ({first['task']})",
                           "goal": "argumentative essay", "audience": f"my teacher (grade {'/'.join(grades)})",
                           "topic": name, "instructions": instructions,
                           "evidence": "the source text given" if first["source_text"].strip() else "the writer's reasoning",
                           "constraints": CONSTRAINTS, "voice": VOICE, "length": length, "split": split,
                           "held_out_genre": False, "human_median_words": median, "human_essays": len(group)})
    folder = LOCAL / "prompts"
    for split, rows in out.items():
        write_jsonl(folder / f"persuade-{split}.jsonl", rows)
    lock_path = folder / "lock.json"
    lock_path.write_text(json.dumps({"seed": SEED + 1, "source_csv_sha256": sha256_file(csv_path), "files": {
        f"data/generation_eval/prompts/persuade-{s}.jsonl": sha256_file(folder / f"persuade-{s}.jsonl") for s in out}},
        indent=1), encoding="utf-8")
    print(f"PERSUADE prompts: dev {len(out['dev'])}, eval {len(out['eval'])}")


def check():
    """Fails if any locked prompt file changed since it was built."""
    problems = []
    for lock_path in (PROMPTS / "lock.json", LOCAL / "prompts" / "lock.json"):
        if not lock_path.exists():
            continue
        for rel, digest in json.loads(lock_path.read_text(encoding="utf-8"))["files"].items():
            path = ROOT / rel
            if not path.exists() or sha256_file(path) != digest:
                problems.append(rel)
    print("prompt lock: " + ("OK" if not problems else f"CHANGED {problems}"))
    return not problems


def load(split, families=("quill-existing", "quill-genre", "persuade")):
    """All prompts of a split, from whichever families are built."""
    rows = []
    for path in (PROMPTS / f"quill-{split}.jsonl", LOCAL / "prompts" / f"persuade-{split}.jsonl"):
        if path.exists():
            rows += [r for r in read_jsonl(path) if r["family"] in families]
    return rows


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "build":
        build()
    elif cmd == "persuade":
        persuade(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        sys.exit(0 if check() else 1)
