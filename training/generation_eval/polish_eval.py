"""Polish evaluation (polish_plan.md): 40 editor-dev essays polished, judged against the line editor.

    .venv\\Scripts\\python training\\generation_eval\\polish_eval.py run        # polish the sample -> polish-dev.jsonl
    .venv\\Scripts\\python training\\generation_eval\\polish_eval.py packets    # blind judge packets (X/Y per essay)
    .venv\\Scripts\\python training\\generation_eval\\polish_eval.py score      # judges + content check -> polish-dev-summary.json

Each essay goes through editor.polish_stream, the app's own call, with the voice measured from the
essay for a writer with no profile and no goal; every polished paragraph is taken (an upper bound).
The comparison is the same essay from editor-dev-C.jsonl (every line-editor suggestion applied).
Judge ratings are model judgments (Claude), never human ratings.
"""
import asyncio
import json
import random
import statistics
import sys

from common import read_jsonl, write_jsonl
import generate  # loads quill.env and backend modules the same way  # noqa: F401
import editor  # noqa: E402
import voices  # noqa: E402
import editor_sets  # noqa: E402
from config import OVERVIEW_MODEL, POLISH_OPTIONS  # noqa: E402

SEED = 20261025
N = 40
OUT = editor_sets.OUT / "polish-dev.jsonl"
PACKETS = editor_sets.OUT / "polish-judges"
DIMENSIONS = ["meaning", "errors", "flow", "voice", "restraint"]


def sample():
    rows = editor_sets.load("editor-dev")
    return sorted(random.Random(SEED).sample(rows, N), key=lambda r: r["human_id"])


async def polish_text(text):
    voice = voices.describe(generate.FRESH_PROFILE, text)
    paragraphs = []
    async for e in editor.polish_stream(text, voice, ""):
        if e["type"] == "paragraph":
            paragraphs.append(e)
    return paragraphs


def run():
    start = generate.environment()["ollama_version"]
    done = {r["human_id"]: r for r in read_jsonl(OUT)} if OUT.exists() else {}
    rows = sample()
    for n, r in enumerate(rows):
        if r["human_id"] in done:
            continue
        if generate.environment()["ollama_version"] != start:
            raise SystemExit("Ollama changed mid-run; stopping. Rerun to resume.")
        paragraphs = asyncio.run(polish_text(r["text"]))
        done[r["human_id"]] = {"human_id": r["human_id"], "source": r["source"], "before": r["text"],
                               "text": "\n\n".join(p["revised"] for p in paragraphs),
                               "paragraphs": [{k: p[k] for k in ("original", "revised", "checks")} for p in paragraphs],
                               "model": OVERVIEW_MODEL, "options": POLISH_OPTIONS, "ollama_version": start}
        write_jsonl(OUT, [done[k["human_id"]] for k in rows if k["human_id"] in done], overwrite=True)  # resumable
        warned = sum(1 for p in paragraphs if p["checks"]["warnings"])
        print(f"  {n + 1}/{len(rows)} {r['human_id']}: {len(paragraphs)} paragraphs, {warned} with warnings", flush=True)


def versions():
    polished = {r["human_id"]: r for r in read_jsonl(OUT)}
    edited = {r["human_id"]: r for r in read_jsonl(editor_sets.OUT / "editor-dev-C.jsonl")}
    return [(hid, polished[hid]["before"], edited[hid]["text"], polished[hid]["text"]) for hid in sorted(polished)]


def packets():
    """Two packets of 20 essays; each essay shows the original and the two revisions as X and Y in a
    per-essay random order. The key stays outside the packets."""
    PACKETS.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED + 1)
    key, items = {}, []
    for n, (hid, before, edited, polished) in enumerate(versions()):
        item = f"e{n + 1:02d}"
        flip = rng.random() < 0.5
        key[item] = {"human_id": hid, "X": "polish" if flip else "editor", "Y": "editor" if flip else "polish"}
        x, y = (polished, edited) if flip else (edited, polished)
        items.append(f"## {item}\n\n### Original\n\n{before}\n\n### X\n\n{x}\n\n### Y\n\n{y}\n")
    for p in range(2):
        (PACKETS / f"packet-{p + 1}.md").write_text("\n---\n\n".join(items[p * 20:(p + 1) * 20]), encoding="utf-8")
    (PACKETS / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(items)} essays in 2 packets under {PACKETS}")


def score():
    key = json.loads((PACKETS / "key.json").read_text(encoding="utf-8"))
    ratings = {"editor": {d: [] for d in DIMENSIONS}, "polish": {d: [] for d in DIMENSIONS}}
    low_meaning = set()
    per_item = {}
    for path in sorted(PACKETS.glob("judge-*/ratings-*.json")):
        for item, r in json.loads(path.read_text(encoding="utf-8")).items():
            for label in ("X", "Y"):
                arm = key[item][label]
                for d in DIMENSIONS:
                    ratings[arm][d].append(r[label][d])
                if arm == "polish" and r[label]["meaning"] <= 2:
                    low_meaning.add(item)
                per_item.setdefault(item, {}).setdefault(arm, []).append(r[label]["meaning"])
    means = {arm: {d: round(statistics.mean(v), 2) for d, v in dims.items() if v} for arm, dims in ratings.items()}
    polished = {r["human_id"]: r for r in read_jsonl(OUT)}
    paras = [p for r in polished.values() for p in r["paragraphs"]]
    kinds = {k: sum(1 for p in paras if any(w.startswith(k) for w in p["checks"]["warnings"])) / len(paras)
             for k in ("A number", "A name", "A quotation", "Much of your wording", "It's")}
    caught = [item for item in low_meaning
              if any(p["checks"]["warnings"] for p in polished[key[item]["human_id"]]["paragraphs"])]
    m = means["polish"]
    rules = {
        "meaning >= 4.0": m["meaning"] >= 4.0,
        "meaning <= 2 on at most 10% of essays": len(low_meaning) <= 0.1 * len(key),
        "errors >= editor - 0.25": m["errors"] >= means["editor"]["errors"] - 0.25,
        "flow > editor": m["flow"] > means["editor"]["flow"],
        "voice >= 3.0": m["voice"] >= 3.0,
    }
    summary = {
        "essays": len(key), "judge_files": len(list(PACKETS.glob("judge-*/ratings-*.json"))),
        "means": means, "polish_meaning_le2_essays": sorted(low_meaning),
        "low_meaning_with_a_warning": sorted(caught),
        "paragraphs": len(paras), "paragraphs_with_any_warning": round(sum(1 for p in paras if p["checks"]["warnings"]) / len(paras), 3),
        "warning_rates": {k: round(v, 3) for k, v in kinds.items()},
        "mean_kept_words": round(statistics.mean(p["checks"]["kept_words"] for p in paras), 3),
        "mean_length_change": round(statistics.mean(p["checks"]["length_change"] for p in paras), 3),
        "rules": rules, "ship_as_built": all(rules.values()),
    }
    (editor_sets.OUT / "polish-dev-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    {"run": run, "packets": packets, "score": score}[sys.argv[1]]()
