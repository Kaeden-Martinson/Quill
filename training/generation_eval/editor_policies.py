"""Detector side effects of each editing policy, on a set of human essays (editor_plan.md).

    .venv-train\\Scripts\\python training\\generation_eval\\editor_policies.py SET --detector NAME
    SET: editor-dev, or editor-holdout (needs QUILL_GEN_UNSEAL=1; opened once, at the end)

Rebuilds each essay from the edits pipeline C recorded (human/editor/SET-C.jsonl), localized by
backend/localize.py, under each policy: original; everything; accept-all fixes (typo + grammar
pieces); typos mode (typo pieces). Rebuilding with every piece must reproduce the recorded edited text
(checked). Scores every version with one detector per process (models left in GPU memory slowed the
next one ~50x) and writes data/generation_eval/detectors/policies-SET-NAME.json.
"""
import json
import sys
from pathlib import Path

from common import LOCAL, require_unsealed
import editor_sets
import stats as S

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))
import localize  # noqa: E402

POLICIES = {"original": set(), "everything": None, "accept-all fixes": {"typo", "grammar"}, "typos mode": {"typo"}}


def split_paragraphs(text):   # editor.split_paragraphs
    import re
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def rebuild(row, kinds):
    paras = split_paragraphs(row["before"])
    originals = list(paras)
    finals = split_paragraphs(row["text"])   # each paragraph with every edit applied
    for e in row["edits_applied"]:
        i = e["paragraph"]
        s = {k: e[k] for k in ("original", "revised", "reason", "category")}
        for p in localize.localize(originals[i], s, finals[i]):
            if (kinds is None or p["kind"] in kinds) and p["original"] in paras[i]:
                paras[i] = paras[i].replace(p["original"], p["revised"], 1)
    return "\n\n".join(paras)


def main(set_name, detector):
    if set_name != "editor-dev":
        require_unsealed("eval", f"editor_policies.py {set_name}")
    rows = [json.loads(l) for l in open(editor_sets.OUT / f"{set_name}-C.jsonl", encoding="utf-8")]
    mismatches = [r["human_id"] for r in rows if rebuild(r, None) != r["text"]]
    print(f"{len(rows)} essays; rebuild mismatches with every piece: {len(mismatches)} {mismatches[:3]}")
    versions = {pol: [r["before"] if kinds == set() else rebuild(r, kinds) for r in rows] for pol, kinds in POLICIES.items()}
    import torch
    import run_local_detectors as R
    det = R.DETECTORS[detector]("cuda" if torch.cuda.is_available() else "cpu")
    scores = {pol: [det.score(t) for t in texts] for pol, texts in versions.items()}
    base = [s >= 0.5 for s in scores["original"]]
    out = {"set": set_name, "detector": detector, "essays": len(rows), "rebuild_mismatches": mismatches, "policies": {}}
    for pol, sc in scores.items():
        f = [s >= 0.5 for s in sc]
        w = S.wilson(sum(f), len(f))
        b = sum(1 for x, y in zip(base, f) if not x and y)
        c = sum(1 for x, y in zip(base, f) if x and not y)
        out["policies"][pol] = {"flagged": sum(f), "n": len(f), "rate": round(w[0], 4),
                                "wilson95": [round(w[1], 4), round(w[2], 4)], "became_ai": b, "became_human": c,
                                "mcnemar_p": S.mcnemar_exact(b, c), "scores": [round(s, 5) for s in sc]}
        print(f"  {detector:15} {pol:17} {sum(f):3}/{len(f)} = {w[0]:.1%} [{w[1]:.1%}, {w[2]:.1%}]  +{b}/-{c}", flush=True)
    dest = LOCAL / "detectors" / f"policies-{set_name}-{detector}.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {dest}")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0], args[args.index("--detector") + 1])
