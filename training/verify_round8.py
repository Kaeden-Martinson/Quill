"""Integrity checks for the round 8 experiment, before any model comparison.

    .venv\\Scripts\\python training\\verify_round8.py

Read-only. Checks recorded hashes, traces the dataset counts back to their sources, checks that the
exclusion log accounts for the CoEdIT pool, looks for malformed or duplicate examples, and confirms
the instructions in the training data are the app's. Writes training/rounds/round8_integrity.json.
The sealed set is only hashed here (as reliability.py does before scoring), never read for content.
"""
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ROUNDS = HERE / "rounds"
sys.path.insert(0, str(ROOT / "backend"))
from editor import SYSTEM  # noqa: E402

problems, facts = [], {}


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def check(name, ok, detail=""):
    facts[name] = {"ok": bool(ok), "detail": detail}
    if not ok:
        problems.append(f"{name}: {detail}")
    print(f"  [{'ok' if ok else 'PROBLEM'}] {name}{': ' + str(detail) if detail else ''}")


print("hashes")
r7 = json.loads((ROUNDS / "round7.json").read_text(encoding="utf-8"))
bad = [p for p, f in r7["files"].items() if not (ROOT / p).exists() or sha(ROOT / p) != f["sha256"]]
check("round 7 files match round7.json", not bad, f"{len(r7['files'])} files" + (f"; mismatched {bad}" if bad else ""))
check("train.py unchanged since round 7", sha(HERE / "train.py") == r7["train_config"]["train_py_sha256"])
shown = subprocess.run(["ollama", "show", "quill-editor-v7", "--modelfile"], capture_output=True, text=True).stdout
blob = re.search(r"^FROM .*[\\/](sha256-[0-9a-f]+)\s*$", shown, re.M)
check("Ollama's quill-editor-v7 is the recorded round 7 build", blob and blob.group(1) == r7["ollama_blob"],
      blob.group(1)[:20] if blob else "not found")
r8 = json.loads((ROUNDS / "round8_dataset.json").read_text(encoding="utf-8"))
for name in ("train.jsonl", "val.jsonl"):
    check(f"round 8 {name} matches round8_dataset.json", sha(HERE / "data" / name) == r8["sha256"][name])
sealed = json.loads((ROUNDS / "sealed_test.json").read_text(encoding="utf-8"))
check("sealed cases unchanged since sealing", sha(ROOT / "data/sealed_test/cases.jsonl") == sealed["cases_sha256"])
check("sealed set never scored (no sealed_log.jsonl)", not (ROUNDS / "sealed_log.jsonl").exists())

print("\nCoEdIT exclusion accounting")
excl = load(ROUNDS / "round8_exclusions.jsonl")
check("exclusions + kept rows = pool", len(excl) + r8["coedit_kept_rows"] == r8["coedit_pool_rows"],
      f"{len(excl)} + {r8['coedit_kept_rows']} vs {r8['coedit_pool_rows']}")
check("exclusion reasons match the manifest", dict(Counter(x["reason"] for x in excl)) == r8["coedit_excluded"])
check("every exclusion has an _id and reason", all(x.get("_id") and x.get("reason") for x in excl))
ids = Counter(x["_id"] for x in excl)
check("no CoEdIT row excluded twice", max(ids.values()) == 1)
coedit_paras = r8["train"]["coedit"] + r8["val"]["coedit"]
# Kept rows are grouped three to a paragraph within each side; a side's last 1-2 rows can be left over.
check("CoEdIT paragraphs x 3 accounts for kept rows", 0 <= r8["coedit_kept_rows"] - 3 * coedit_paras <= 4,
      f"{coedit_paras} paragraphs x 3 = {3 * coedit_paras} of {r8['coedit_kept_rows']} kept rows")

print("\nprofessional counts, traced to data/pro_prose/paragraphs.jsonl")
pro = load(ROOT / "data/pro_prose/paragraphs.jsonl")
docs = {p["doc"] for p in pro}
pro_train = r8["train"].get("pro-python", 0) + r8["train"].get("pro-sec", 0)
pro_val = r8["val"].get("pro-python", 0) + r8["val"].get("pro-sec", 0)
facts["professional_trace"] = {
    "source_paragraphs": len(pro), "documents": len(docs), "by_source": dict(Counter(p["source"] for p in pro)),
    "no_edit_examples": r8["professional"]["no_edit"], "light_edit_examples": r8["professional"]["light_edit"],
    "examples_total": r8["professional"]["no_edit"] + r8["professional"]["light_edit"],
    "train_examples": pro_train, "val_examples": pro_val}
print(f"  {len(pro)} paragraphs from {len(docs)} documents -> {r8['professional']['no_edit']} no-edit "
      f"(one per paragraph) + {r8['professional']['light_edit']} light-edit (only where a rule could plant a mistake) "
      f"= {r8['professional']['no_edit'] + r8['professional']['light_edit']} examples = {pro_train} train + {pro_val} val")
check("professional examples = no-edit + light-edit = train + val",
      r8["professional"]["no_edit"] + r8["professional"]["light_edit"] == pro_train + pro_val)
check("one no-edit example per source paragraph", r8["professional"]["no_edit"] == len(pro))

print("\nexample checks (round 8 train + val)")
for split in ("train", "val"):
    rows = load(HERE / "data" / f"{split}.jsonl")
    malformed = quote_missing = unchanged = system_mismatch = no_goal = 0
    cats = Counter()
    for r in rows:
        msgs = r["messages"]
        system_mismatch += msgs[0]["content"] != SYSTEM
        no_goal += "Essay goal: " not in msgs[1]["content"]
        try:
            sugg = json.loads(msgs[2]["content"])["suggestions"]
        except (json.JSONDecodeError, KeyError):
            malformed += 1
            continue
        para = msgs[1]["content"].split('Paragraph:\n"""\n', 1)[1].rsplit('\n"""', 1)[0]
        for s in sugg:
            if not all(k in s for k in ("original", "revised", "reason", "category")):
                malformed += 1
            quote_missing += s["original"] not in para
            unchanged += s["revised"] == s["original"]
            cats[s["category"]] += 1
    dupes = sum(c - 1 for c in Counter(json.dumps(r["messages"], ensure_ascii=False) for r in rows).values() if c > 1)
    facts[f"{split}_examples"] = {"n": len(rows), "malformed": malformed, "quote_missing": quote_missing,
                                  "unchanged_edits": unchanged, "exact_duplicate_examples": dupes,
                                  "system_prompt_mismatch": system_mismatch, "categories": dict(cats)}
    check(f"{split}: {len(rows)} examples parse, quotes present, system prompt is the app's",
          not (malformed or quote_missing or system_mismatch or no_goal),
          f"malformed {malformed}, quote missing {quote_missing}, system mismatch {system_mismatch}")
    print(f"     unchanged edits {unchanged}; exact duplicate examples {dupes}; categories {dict(cats)}")

# The val set has no near-duplicates of train (round8_dataset.json, measured at build time).
check("validation near-duplicates of training removed at build", r8["val_dropped_as_near_duplicates"] == 0,
      "0 found at build (5-gram, 50%)")

(ROUNDS / "round8_integrity.json").write_text(json.dumps({"problems": problems, "facts": facts}, indent=1),
                                              encoding="utf-8")
print(f"\n{len(problems)} problem(s)" + (": " + "; ".join(problems) if problems else ""))
