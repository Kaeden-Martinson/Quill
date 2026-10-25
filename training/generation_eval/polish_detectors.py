"""Detector diagnostic for the Polish evaluation (polish_plan.md, measure 3): the 40 essays as the
student wrote them, after the line editor (every suggestion), and after Polish (every paragraph taken).

    .venv-train\\Scripts\\python training\\generation_eval\\polish_detectors.py --detector desklib

A diagnostic only: polished paragraphs are AI-written and are expected to be flagged. Nothing is tuned
against these numbers. One detector per process (see editor_diagnosis.py). Ollama must be idle.
"""
import json
import sys

import torch

from common import LOCAL, read_jsonl
import editor_sets
import run_local_detectors as R
import stats as S


def main(only):
    polished = read_jsonl(editor_sets.OUT / "polish-dev.jsonl")
    edited = {r["human_id"]: r["text"] for r in read_jsonl(editor_sets.OUT / "editor-dev-C.jsonl")}
    versions = {"original": [r["before"] for r in polished],
                "line editor, everything": [edited[r["human_id"]] for r in polished],
                "polish, every paragraph": [r["text"] for r in polished]}
    det = R.DETECTORS[only]("cuda" if torch.cuda.is_available() else "cpu")
    flags = {v: [det.score(t) >= 0.5 for t in texts] for v, texts in versions.items()}
    out = {}
    for v, f in flags.items():
        w = S.wilson(sum(f), len(f))
        out[v] = {"flagged": sum(f), "n": len(f), "rate": round(w[0], 4), "wilson95": [round(w[1], 4), round(w[2], 4)]}
        print(f"  {only:15} {v:26} {sum(f):3}/{len(f)} = {w[0]:.1%} [{w[1]:.1%}, {w[2]:.1%}]")
    dest = LOCAL / "detectors" / f"polish-dev-{only}.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--detector") + 1])
