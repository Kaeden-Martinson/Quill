"""Round 8 training data: round 7's sources with traced exclusions, a split by source, consistent goal
labels, and professional prose. Plan and selection rules: training/rounds/round8_plan.md.

    .venv-train\\Scripts\\python training\\build_dataset_r8.py

Writes training/data/{train,val}.jsonl (what train.py reads), training/rounds/round8_exclusions.jsonl
(every excluded CoEdIT example with its _id and reason) and training/rounds/round8_dataset.json
(composition, counts and hashes). build_dataset.py is left as it was so round 7 can be rebuilt.
"""
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from datasets import load_dataset

import audit_coedit
import build_dataset as r7
import errors
import writing_metrics as wm
from reasons import all_changes_reason, change_count, main_change, reason_for

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ROUNDS = HERE / "rounds"
sys.path.insert(0, str(ROOT / "backend"))
from style import describe_voice, profile_stats  # noqa: E402

UNSPECIFIED = "not specified"
VAL_SHARE = 20  # 1 in 20 sources goes to validation


def in_val(key):
    """Deterministic split by source: the same paragraph, sentence or document always lands on the
    same side, whatever variants are made of it."""
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % VAL_SHARE == 0


def example(paragraph, suggestions, voice, goal=UNSPECIFIED):
    return r7.example(paragraph, suggestions, voice=voice, goal=goal)


# ---------- CoEdIT, with every exclusion logged ----------

def corrupted(src, tgt):
    """A grammar target that keeps the wrong word next to its fix ("give me advise advice")."""
    a, b = wm.words(src), wm.words(tgt)
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "insert" and i1 > 0 and j2 - j1 <= 3:
            if any(SequenceMatcher(None, a[i1 - 1], w).ratio() >= 0.7 and a[i1 - 1] != w for w in b[j1:j2]):
                return True
    return False


def coedit_rows(limit, log):
    rng = random.Random(7)
    rows = [r for r in load_dataset("grammarly/coedit", split="train")
            if r["task"] in r7.TASKS and rng.random() < r7.KEEP_SHARE.get(r["task"], 1.0)]
    rng.shuffle(rows)
    rows = rows[:limit * 3]  # the same pool round 7 drew from
    pairs = [(r, r7.strip_instruction(r["src"]), r["tgt"].strip()) for r in rows]
    freq = Counter(w for _, s, t in pairs for w in wm.words(s) + wm.words(t))
    targets = defaultdict(set)
    for _, s, t in pairs:
        targets[s].add(t)
    seen, kept = set(), []
    for r, src, tgt in pairs:
        reason = None
        _, flags = audit_coedit.classify(src, tgt, freq)
        if len(targets[src]) > 1:
            reason = "conflicting_targets"
        elif (src, tgt) in seen:
            reason = "duplicate_pair"
        elif "instruction_leftover" in flags:
            reason = "instruction_leftover"
        elif r["task"] in ("simplification", "clarity") and ("adds_content" in flags or "drops_content" in flags):
            reason = "content_change"
        elif r["task"] == "gec" and corrupted(src, tgt):
            reason = "corrupted_target"
        seen.add((src, tgt))
        if reason:
            log.append({"_id": r["_id"], "task": r["task"], "reason": reason, "src": src[:300], "tgt": tgt[:300]})
        else:
            kept.append((r, src, tgt))
    return kept


def coedit_examples(kept):
    """Round 7's grouping (three sentences to a pseudo-paragraph, some left clean), done separately
    inside each side of the split so no sentence feeds both."""
    rng = random.Random(8)
    out = {"train": [], "val": []}
    sides = {"train": [k for k in kept if not in_val("coedit:" + k[0]["_id"])],
             "val": [k for k in kept if in_val("coedit:" + k[0]["_id"])]}
    for side, items in sides.items():
        for i in range(0, len(items) - 2, 3):
            sentences, suggestions = [], []
            all_clean = rng.random() < r7.CLEAN_PARAGRAPH_SHARE
            for r, src, tgt in items[i:i + 3]:
                category, fallback = r7.TASKS[r["task"]]
                change = main_change(src, tgt)
                if all_clean or change is None or " ".join(src.split()) == " ".join(tgt.split()) or rng.random() < 0.25:
                    sentences.append(tgt)
                    continue
                _, old, new = change
                if change_count(src, tgt) == 1:
                    reason = reason_for(category, src, tgt) if len(old) + len(new) <= 8 else None
                else:
                    reason = all_changes_reason(category, src, tgt)
                sentences.append(src)
                suggestions.append({"original": src, "revised": tgt, "reason": reason or fallback, "category": category})
            out[side].append(("coedit", example(" ".join(sentences), suggestions, r7.GENERIC_VOICE)))
    return out


# ---------- casual paragraphs: split first, then variants ----------

def casual_examples(variants=3):
    rng = random.Random(9)
    paragraphs = [json.loads(line)["paragraph"].translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})).strip()
                  for line in open(r7.CASUAL, encoding="utf-8-sig")]
    used = {rule[0]: 0 for rule in errors.RULES}
    common = {"its-it's", "your-you're", "a-lot", "then-than", "there-their"}
    cap = lambda rule: 260 if rule == "its-it's" else 160 if rule in common else 110  # noqa: E731  as round 7
    out = {"train": [], "val": []}
    for paragraph in paragraphs:
        side = "val" if in_val("casual:" + paragraph) else "train"
        voice = describe_voice(profile_stats([paragraph]))
        for _ in range(variants):
            text, suggestions = paragraph, []
            rules = [r for r in errors.applicable(paragraph) if used[r] < cap(r)]
            rng.shuffle(rules)
            rules.sort(key=lambda name: used[name])
            if rules and rng.random() > r7.CLEAN_PARAGRAPH_SHARE:
                want = 2 if rng.random() < 0.45 else 1
                same_sentence = want == 2 and rng.random() < 0.5
                planted = 0
                for rule in rules:
                    if planted == want:
                        break
                    within = suggestions[0]["original"] if same_sentence and suggestions else None
                    result = errors.plant(text, rule, rng, within=within)
                    if not result:
                        continue
                    new_text, s = result
                    if within:
                        first = suggestions[0]
                        if s["revised"] != first["original"]:
                            continue
                        suggestions[0] = {"original": s["original"], "revised": first["revised"],
                                          "reason": f"{first['reason']} {s['reason']}", "category": first["category"]}
                    elif all(o["original"] not in s["original"] and s["original"] not in o["original"]
                             and o["original"] in new_text for o in suggestions):
                        suggestions.append(s)
                    else:
                        continue
                    text = new_text
                    used[rule] += 1
                    planted += 1
            out[side].append(("casual", example(text, suggestions, voice)))  # goal: not specified
    return out


# ---------- professional prose: no-edit and light-edit ----------

def pro_examples():
    rng = random.Random(10)
    out = {"train": [], "val": []}
    counts = Counter()
    for line in open(ROOT / "data" / "pro_prose" / "paragraphs.jsonl", encoding="utf-8"):
        row = json.loads(line)
        side = "val" if in_val("pro:" + row["doc"]) else "train"
        text, goal = row["text"], row["genre"]
        voice = describe_voice(profile_stats([text]))
        # No-edit: the published paragraph as written is the right answer.
        out[side].append((f"pro-{row['source']}", example(text, [], voice, goal)))
        counts["no_edit"] += 1
        # Light edit: a planted mistake (two, sometimes) and only that fixed.
        rules = errors.applicable(text)
        rng.shuffle(rules)
        suggestions, planted = [], 0
        want = 2 if rng.random() < 0.3 else 1
        for rule in rules:
            if planted == want:
                break
            result = errors.plant(text, rule, rng)
            if not result:
                continue
            new_text, s = result
            if any(o["original"] in s["original"] or s["original"] in o["original"] or o["original"] not in new_text
                   for o in suggestions):
                continue
            suggestions.append(s)
            text = new_text
            planted += 1
        if suggestions:
            out[side].append((f"pro-{row['source']}", example(text, suggestions, voice, goal)))
            counts["light_edit"] += 1
    return out, counts


def near_duplicate_val(train_rows, val_rows):
    """Validation examples sharing half their word 5-grams with any training paragraph."""
    paragraph = lambda ex: ex["messages"][1]["content"].split('Paragraph:\n"""\n', 1)[1]  # noqa: E731
    from audit_pipeline import near_duplicates
    hits = near_duplicates([paragraph(e) for _, e in val_rows], [paragraph(e) for _, e in train_rows])
    return [i for i, h in enumerate(hits) if h]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(limit=8500):
    ROUNDS.mkdir(exist_ok=True)
    log = []
    kept = coedit_rows(limit, log)
    parts = [coedit_examples(kept), casual_examples()]
    pro, pro_counts = pro_examples()
    parts.append(pro)
    train = [x for p in parts for x in p["train"]]
    val = [x for p in parts for x in p["val"]]
    feedback = [("feedback", e) for e in r7.app_examples()] * 3  # as round 7: weighted up, train only
    train += feedback
    dropped = near_duplicate_val(train, val)
    val = [v for i, v in enumerate(val) if i not in set(dropped)]
    rng = random.Random(11)
    rng.shuffle(train)
    rng.shuffle(val)
    out = HERE / "data"
    out.mkdir(exist_ok=True)
    for name, rows in (("train", train), ("val", val)):
        with open(out / f"{name}.jsonl", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(e, ensure_ascii=False) + "\n" for _, e in rows)
    with open(ROUNDS / "round8_exclusions.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in log)
    edits = lambda rows: sum(len(json.loads(e["messages"][2]["content"])["suggestions"]) for _, e in rows)  # noqa: E731
    manifest = {
        "coedit_pool_rows": limit * 3,
        "coedit_excluded": dict(Counter(x["reason"] for x in log)),
        "coedit_excluded_by_task": {f"{t}/{r}": c for (t, r), c in Counter((x["task"], x["reason"]) for x in log).items()},
        "coedit_kept_rows": len(kept),
        "train": dict(Counter(s for s, _ in train)), "val": dict(Counter(s for s, _ in val)),
        "train_examples": len(train), "val_examples": len(val),
        "train_edits": edits(train), "val_edits": edits(val),
        "val_dropped_as_near_duplicates": len(dropped),
        "professional": dict(pro_counts),
        "goal_labels": dict(Counter(e["messages"][1]["content"].split("Essay goal: ", 1)[1].split("\n", 1)[0]
                                    for _, e in train)),
        "sha256": {"train.jsonl": sha(out / "train.jsonl"), "val.jsonl": sha(out / "val.jsonl")},
    }
    (ROUNDS / "round8_dataset.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
