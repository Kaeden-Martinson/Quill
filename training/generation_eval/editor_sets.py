"""Fresh human-essay sets for editor work (2026-10-24), drawn from essays no earlier set used.

    .venv\\Scripts\\python training\\generation_eval\\editor_sets.py build

- editor-dev (200): for diagnosing the editor and choosing changes.
- editor-holdout (300): locked; opened once, to confirm the final editor (QUILL_GEN_UNSEAL=1, logged).
  Nothing is tuned on it.

Both come from the same licensed Tier A sources as the other controls (sources.json: PERSUADE 2.0 and
ELLIPSE, CC BY-NC-SA 4.0, local detectors only) with the same exclusions (malformed text, under 150
words, ELLIPSE essays also in PERSUADE), minus every essay already sampled into dev or eval. Each set
is 60% PERSUADE and 40% ELLIPSE (as in the eval set), drawn with a fixed seed. Written to
data/generation_eval/human/editor/ (local), with the draw recorded beside it.
"""
import json
import random
import sys

from common import HUMAN, LOCAL, sha256_file, words, write_jsonl
import human as H

SEED = 20261025
SIZES = {"editor-dev": 200, "editor-holdout": 300}
SHARE_PERSUADE = 0.6
OUT = HUMAN / "editor"


def pool(name):
    path = next((LOCAL / "sources" / name).glob("*.csv"))
    src = H.SOURCES[name]
    shared = H.persuade_ids() if name == "ellipse" else set()
    used = {r["source_id"] for r in H.load() if r["source"] == name}
    rows = []
    for r in H.ADAPTERS[src["adapter"]](path):
        if r["source_id"] in used or r["source_id"] in shared:
            continue
        if H.malformed(r["text"]) or words(r["text"]) < H.MIN_WORDS:
            continue
        rows.append(r)
    return sorted(rows, key=lambda r: r["source_id"]), path


def build():
    rng = random.Random(SEED)
    draws, record = {}, {"seed": SEED, "sources": {}}
    for name in ("persuade", "ellipse"):
        rows, path = pool(name)
        rng.shuffle(rows)
        record["sources"][name] = {"source_file_sha256": sha256_file(path), "eligible_unused": len(rows)}
        draws[name] = rows
    for set_name, size in SIZES.items():
        k_p = round(size * SHARE_PERSUADE)
        chosen = [("persuade", r) for r in draws["persuade"][:k_p]] + [("ellipse", r) for r in draws["ellipse"][:size - k_p]]
        draws["persuade"], draws["ellipse"] = draws["persuade"][k_p:], draws["ellipse"][size - k_p:]
        out = [{"human_id": f"h-{src}-{r['source_id']}", "source": src, "source_id": r["source_id"],
                "tier": H.SOURCES[src]["tier"], "license": H.SOURCES[src]["license"],
                "permitted_use": H.SOURCES[src]["permitted_use"], "provenance_method": H.SOURCES[src]["provenance_method"],
                "collected": H.SOURCES[src]["collected"], "genre": r["genre"], "topic": r["topic"],
                "grade": r.get("grade"), "ell": r.get("ell"), "provider": r.get("provider"), "words": words(r["text"]),
                "edit_history": "unknown", "ai_assistance": "unknown", "split": set_name, "text": r["text"].strip()}
               for src, r in chosen]
        write_jsonl(OUT / f"{set_name}.jsonl", out)
        record[set_name] = {"essays": len(out), "persuade": k_p, "ellipse": size - k_p,
                            "sha256": sha256_file(OUT / f"{set_name}.jsonl")}
    (OUT / "sets.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    print(json.dumps(record, indent=1))


def load(set_name):
    return [json.loads(l) for l in open(OUT / f"{set_name}.jsonl", encoding="utf-8")]


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        build()
