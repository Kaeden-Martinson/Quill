"""Which kinds of editor correction move detector labels on human essays? (detector track Q3 follow-up)

    set QUILL_GEN_UNSEAL=1   (only if SET is eval or an editor held-out set)
    .venv-train\\Scripts\\python training\\generation_eval\\editor_diagnosis.py SET [C_FILE]
    e.g. editor_diagnosis.py dev            (uses data/generation_eval/human/dev-C.jsonl)

Works from the edits pipeline C already recorded, so the editor isn't rerun. Each applied edit is
classified by what it changes: capitalization only, punctuation only, spelling (one word to a similar
word), or word-level (anything else, including edits that mix types), split into small (at most 2
tokens changed in the edit) and large (3 or more). Each essay is then
rebuilt with only some types applied, and every version is scored by the three local detectors.
Reports false-positive rates per version with Wilson intervals and exact McNemar tests against the
unedited essays. Rebuilding with all types must reproduce the recorded edited text exactly (checked).

This is diagnosis of the editor's side effects on human writing. Its results are not used to make
the editor dodge detectors (plan.md section 0); any editor change has to stand on writing quality.
"""
import difflib
import json
import re
import sys
from pathlib import Path

from common import HUMAN, LOCAL, require_unsealed
import stats as S

TYPES = ("capitalization", "punctuation", "spelling", "word-small", "word-large")
VERSIONS = {
    "original": (),
    "capitalization only": ("capitalization",),
    "punctuation only": ("punctuation",),
    "spelling only": ("spelling",),
    "mechanical (cap + punct + spelling)": ("capitalization", "punctuation", "spelling"),
    "word-level, small (1-2 tokens) only": ("word-small",),
    "word-level, large (3+ tokens) only": ("word-large",),
    "mechanical + small word-level": ("capitalization", "punctuation", "spelling", "word-small"),
    "all edits": TYPES,
}
TOKEN = re.compile(r"\w+|[^\w\s]")


def split_paragraphs(text):   # editor.split_paragraphs
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def edit_type(original, revised):
    a, b = TOKEN.findall(original), TOKEN.findall(revised)
    kinds, changed = set(), 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        changed += max(i2 - i1, j2 - j1)
        x, y = a[i1:i2], b[j1:j2]
        if all(not t[0].isalnum() for t in x + y):
            kinds.add("punctuation")
        elif op == "replace" and len(x) == len(y) and all(p.lower() == q.lower() for p, q in zip(x, y)):
            kinds.add("capitalization")
        elif (op == "replace" and len(x) == 1 and len(y) == 1
              and difflib.SequenceMatcher(a=x[0].lower(), b=y[0].lower()).ratio() >= 0.75):
            kinds.add("spelling")
        else:
            kinds.add("word")
    if not kinds:   # only spacing changed ("Venice,Italy" -> "Venice, Italy"): mechanical, like punctuation
        return "punctuation" if original != revised else None
    if "word" in kinds:   # small: at most 2 tokens changed in the whole edit
        return "word-small" if changed <= 2 else "word-large"
    return "spelling" if "spelling" in kinds else \
        "capitalization" if "capitalization" in kinds else "punctuation"


SPACED = re.compile(r"\s+|\w+|[^\w\s]")


def hunk_apply(original, revised, keep_hunk):
    """original with only the diff hunks keep_hunk(size) accepts applied; size counts non-space tokens.
    Whitespace is kept as tokens so the result is exact text (all hunks kept == revised)."""
    a, b = SPACED.findall(original), SPACED.findall(revised)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out += a[i1:i2]
            continue
        size = max(sum(1 for x in a[i1:i2] if not x.isspace()), sum(1 for x in b[j1:j2] if not x.isspace()))
        out += b[j1:j2] if keep_hunk(size) else a[i1:i2]
    return "".join(out)


def rebuild_hunks(row, keep_edit, keep_hunk):
    paras = split_paragraphs(row["before"])
    for e in row["edits_applied"]:
        if keep_edit(e) and e["original"] in paras[e["paragraph"]]:
            new = hunk_apply(e["original"], e["revised"], keep_hunk)
            paras[e["paragraph"]] = paras[e["paragraph"]].replace(e["original"], new, 1)
    return "\n\n".join(paras)


def rebuild(row, keep):
    paras = split_paragraphs(row["before"])
    for e in row["edits_applied"]:
        if e["type"] in keep and e["original"] in paras[e["paragraph"]]:
            paras[e["paragraph"]] = paras[e["paragraph"]].replace(e["original"], e["revised"], 1)
    return "\n\n".join(paras)


def load(set_name, c_file=None):
    path = Path(c_file) if c_file else HUMAN / f"{set_name}-C.jsonl"
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    for r in rows:
        for e in r["edits_applied"]:
            e["type"] = edit_type(e["original"], e["revised"])
        assert rebuild(r, TYPES) == r["text"], f"rebuild mismatch for {r['human_id']}"
    return rows


def main(set_name, c_file=None, only=None):
    if set_name not in ("dev", "editor-dev"):
        require_unsealed("eval", f"editor_diagnosis.py {set_name}")
    import torch
    import run_local_detectors as R
    rows = load(set_name, c_file)
    counts = {t: sum(1 for r in rows for e in r["edits_applied"] if e["type"] == t) for t in TYPES}
    print(f"{len(rows)} essays; edits by type: {counts}")
    versions = {v: [rebuild(r, keep) for r in rows] for v, keep in VERSIONS.items()}
    # The app's real bulk path today: "Accept all grammar fixes" takes every grammar-category edit.
    versions["grammar category, any size (today's Accept all)"] = [
        rebuild_hunks(r, lambda e: e.get("category") == "grammar", lambda s: True) for r in rows]
    # Proposed: suggestions split into hunks; bulk accept takes grammar hunks of at most 2 tokens.
    versions["grammar hunks of 1-2 tokens (proposed Accept all)"] = [
        rebuild_hunks(r, lambda e: e.get("category") == "grammar", lambda s: s <= 2) for r in rows]
    versions["rewording hunks of 3+ tokens only"] = [rebuild_hunks(r, lambda e: True, lambda s: s >= 3) for r in rows]
    assert all(rebuild_hunks(r, lambda e: True, lambda s: True) == r["text"] for r in rows), "hunk rebuild mismatch"
    out = {"set": set_name, "essays": len(rows), "edit_types": counts, "detectors": {}}
    for name, cls in R.DETECTORS.items():
        if only and name != only:
            continue
        det = cls("cuda" if torch.cuda.is_available() else "cpu")
        flags = {}
        for v, texts in versions.items():
            flags[v] = [det.score(t) >= 0.5 for t in texts]
            print(f"  ...{name}: scored {v}", flush=True)
        base = flags["original"]
        res = {}
        for v, f in flags.items():
            w = S.wilson(sum(f), len(f))
            b = sum(1 for x, y in zip(base, f) if not x and y)
            c = sum(1 for x, y in zip(base, f) if x and not y)
            res[v] = {"flagged": sum(f), "n": len(f), "rate": round(w[0], 4), "wilson95": [round(w[1], 4), round(w[2], 4)],
                      "became_ai": b, "became_human": c, "mcnemar_p": S.mcnemar_exact(b, c)}
            print(f"  {name:15} {v:38} {sum(f):3}/{len(f)} = {w[0]:.1%} [{w[1]:.1%}, {w[2]:.1%}]  +{b}/-{c}")
        out["detectors"][name] = res
        del det
        torch.cuda.empty_cache()
    dest = LOCAL / "detectors" / f"diagnosis-{set_name}{'-' + only if only else ''}.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {dest}")


if __name__ == "__main__":
    # One detector per process (--detector NAME): models loaded one after another in one process left
    # GPU memory behind, and the next model spilled into slow shared memory (about 50 times slower).
    args = sys.argv[1:]
    only = args[args.index("--detector") + 1] if "--detector" in args else None
    rest = [a for i, a in enumerate(args) if a != "--detector" and (i == 0 or args[i - 1] != "--detector")]
    main(rest[0], rest[1] if len(rest) > 1 else None, only)
