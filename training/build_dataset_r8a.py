"""Round 8a (ablation): round 8's training data with only the professional no-edit examples removed.

    .venv\\Scripts\\python training\\build_dataset_r8a.py

Not a rebuild: it filters round 8's frozen files (training/data-run8), so every other example, its
label and its order relative to the others stay exactly as in round 8. An example is removed when all
of these hold: its target has no edits, its goal line is a professional genre ("annual report (MD&A)"
or "technical documentation"), and its paragraph is word-for-word one of data/pro_prose's source
paragraphs. Light-edit professional examples (planted mistakes, so the paragraph differs) stay.

Validation is copied unchanged, including its professional no-edit examples, so the change is to
training only; that's recorded as a consequence, not hidden.

Writes training/data-r8a/{train,val}.jsonl, training/rounds/round8a_removed.jsonl (one line per removed
example: its line in round 8's train.jsonl and its source paragraph's id) and
training/rounds/round8a_dataset.json (counts before and after, and hashes).
"""
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC, OUT, ROUNDS = HERE / "data-run8", HERE / "data-r8a", HERE / "rounds"
PRO_GOALS = {"annual report (MD&A)", "technical documentation"}


def parts(example):
    user = example["messages"][1]["content"]
    goal = user.split("Essay goal: ", 1)[1].split("\n", 1)[0]
    paragraph = user.split('Paragraph:\n"""\n', 1)[1].rsplit('\n"""', 1)[0]
    edits = json.loads(example["messages"][2]["content"])["suggestions"]
    return goal, paragraph, edits


def kind(example):
    goal, _, edits = parts(example)
    user = example["messages"][1]["content"]
    if goal in PRO_GOALS:
        return "pro no-edit" if not edits else "pro light-edit"
    if "No writing samples yet" in user:
        return "coedit (or feedback) " + ("no-edit" if not edits else "with edits")
    return "casual (or feedback) " + ("no-edit" if not edits else "with edits")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    by_text = {}
    for line in open(ROOT / "data/pro_prose/paragraphs.jsonl", encoding="utf-8"):
        p = json.loads(line)
        by_text[p["text"]] = p
    lines = (SRC / "train.jsonl").read_text(encoding="utf-8").splitlines()
    kept, removed = [], []
    for n, line in enumerate(lines):
        ex = json.loads(line)
        goal, paragraph, edits = parts(ex)
        source = by_text.get(paragraph)
        if not edits and goal in PRO_GOALS and source is not None:
            removed.append({"round8_train_line": n, "pro_id": source["id"], "doc": source["doc"],
                            "source": source["source"], "goal": goal})
        else:
            kept.append(line)
    OUT.mkdir(exist_ok=True)
    (OUT / "train.jsonl").write_text("".join(l + "\n" for l in kept), encoding="utf-8")
    (OUT / "val.jsonl").write_bytes((SRC / "val.jsonl").read_bytes())
    with open(ROUNDS / "round8a_removed.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in removed)
    before = Counter(kind(json.loads(l)) for l in lines)
    after = Counter(kind(json.loads(l)) for l in kept)
    val = Counter(kind(json.loads(l)) for l in (SRC / "val.jsonl").read_text(encoding="utf-8").splitlines())
    no_edit = lambda c: sum(v for k, v in c.items() if k.endswith("no-edit"))  # noqa: E731
    manifest = {
        "derived_from": {"train.jsonl": sha(SRC / "train.jsonl"), "val.jsonl": sha(SRC / "val.jsonl")},
        "removed": len(removed), "removed_by_source": dict(Counter(r["source"] for r in removed)),
        "removed_distinct_paragraphs": len({r["pro_id"] for r in removed}),
        "pro_no_edit_in_round8_val_kept": val.get("pro no-edit", 0),
        "train_before": dict(before), "train_after": dict(after),
        "train_examples_before": len(lines), "train_examples_after": len(kept),
        "no_edit_share_before": round(no_edit(before) / len(lines), 4),
        "no_edit_share_after": round(no_edit(after) / len(kept), 4),
        "steps_at_batch_16": {"before": -(-len(lines) // 16), "after": -(-len(kept) // 16)},
        "sha256": {"train.jsonl": sha(OUT / "train.jsonl"), "val.jsonl": sha(OUT / "val.jsonl")},
    }
    (ROUNDS / "round8a_dataset.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
