"""What each editing mode costs and saves, on the editor's planted-mistake benchmarks (no model run).

    .venv\\Scripts\\python training\\generation_eval\\editor_modes_quality.py

Replays the live editor's logged suggestions (training/eval_results/data-heldout- and
data-confirm-quill-editor-v7.jsonl: 150 paragraphs each, with planted mistakes and clean paragraphs)
through localize.py and each policy, then scores the result exactly as training/reliability.py does:
a planted mistake is fixed when its sentence comes out exactly right; "extra" counts unneeded word
changes; "untouched" is the share of clean paragraphs left without a suggestion shown.

Policies (what the writer ends up with if they accept everything the policy offers in bulk):
- everything: every suggestion applied (what reliability.py reports; pipeline C's upper bound)
- accept-all fixes: typo + grammar pieces, i.e. "Accept all" in any mode (rewrites need a yes)
- typos mode: typo pieces only
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / "backend"))
import localize  # noqa: E402
from reliability import word_changes  # noqa: E402

POLICIES = {"everything": None, "accept-all fixes": {"typo", "grammar"}, "typos mode": {"typo"}}


def replay(path, kinds):
    t = dict(planted=0, fixed=0, perfect=0, clean=0, untouched=0, extra=0, n=0)
    for line in open(path, encoding="utf-8"):
        c = json.loads(line)
        pieces = [p for s in c["suggestions"] for p in localize.localize(c["text"], s)]
        if kinds is not None:
            pieces = [p for p in pieces if p["kind"] in kinds]
        result = c["text"]
        for p in pieces:
            result = result.replace(p["original"], p["revised"], 1)
        fixed = sum(pl["right_sentence"] in result for pl in c["planted"])
        unfixed = len(c["planted"]) - fixed
        t["planted"] += len(c["planted"])
        t["fixed"] += fixed
        t["perfect"] += result == c["correct"]
        t["extra"] += max(0, word_changes(result, c["correct"]) - unfixed)
        t["n"] += 1
        if not c["planted"]:
            t["clean"] += 1
            t["untouched"] += not pieces
    return {"fixed": round(t["fixed"] / t["planted"], 4), "perfect": round(t["perfect"] / t["n"], 4),
            "untouched": round(t["untouched"] / max(t["clean"], 1), 4), "extra": round(t["extra"] / t["n"], 3),
            "planted": t["planted"], "paragraphs": t["n"]}


def main():
    out = {}
    for name in ("data-heldout", "data-confirm"):
        path = HERE.parent / "eval_results" / f"{name}-quill-editor-v7.jsonl"
        out[name] = {pol: replay(path, kinds) for pol, kinds in POLICIES.items()}
        for pol, r in out[name].items():
            print(f"{name:13} {pol:17} fixed {r['fixed']:.1%}  perfect {r['perfect']:.1%}  "
                  f"untouched {r['untouched']:.1%}  extra {r['extra']:.3f}  ({r['planted']} planted, {r['paragraphs']} paragraphs)")
    (HERE / "experiments" / "editor-modes-quality.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
