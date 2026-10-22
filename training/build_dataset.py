"""Builds chat-format training data in exactly the shape the app asks the model for.

Sources:
  1. grammarly/coedit: human-written sentence edits (grammar, clarity, coherence, simplification).
  2. data/quill.db: suggestions your users accepted in the app (grows as people use it).

Output: training/data/train.jsonl and val.jsonl
"""
import json
import random
import sqlite3
import sys
from pathlib import Path

from datasets import load_dataset

import errors
from reasons import all_changes_reason, change_count, main_change, reason_for

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from editor import SYSTEM  # noqa: E402  same instructions the app uses at inference

OUT = Path(__file__).resolve().parent / "data"
DB = ROOT / "data" / "quill.db"
random.seed(7)

# CoEdIT task -> (app category, fallback reason). Skipped tasks:
# - paraphrase rewrites wholesale, which erases voice;
# - neutralize comes from Wikipedia's no-opinion rule ("famous" -> ""), but in a personal essay
#   the opinion is the writer's voice; the first fine-tune learned to flatten "go great" to "go well".
TASKS = {
    "gec": ("grammar", "Fixes a grammar or spelling error without changing your wording."),
    "clarity": ("clarity", "Makes the meaning easier to follow on the first read."),
    "coherence": ("flow", "Connects the ideas so the sentence reads more smoothly."),
    # Simplification edits are sometimes longer (spelling a contraction out), so this must not say "fewer".
    "simplification": ("concision", "Makes the sentence simpler and easier to read."),
}
CLEAN_PARAGRAPH_SHARE = 0.15  # paragraphs with nothing to fix, so the model learns to leave them alone
# Coherence edits join short sentences with connectors. Fine for Wikipedia prose, but round 2 used
# them to merge deliberate fragments ("Eleven miles.") and add "But" to "I tried. I failed. I tried
# again." Keep only some so joining sentences isn't the model's default move.
KEEP_SHARE = {"coherence": 0.5}
GENERIC_VOICE = "No writing samples yet; keep the writer's existing tone."


def strip_instruction(src):
    # CoEdIT sources look like "Fix grammar: <sentence>"
    return src.split(":", 1)[1].strip() if ":" in src else src.strip()


def example(paragraph, suggestions, voice=GENERIC_VOICE, goal="not specified"):
    user = f"Writer's voice:\n{voice}\n\nEssay goal: {goal}\n\nParagraph:\n\"\"\"\n{paragraph}\n\"\"\""
    return {"messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
        {"role": "assistant", "content": json.dumps({"suggestions": suggestions}, ensure_ascii=False)},
    ]}


def coedit_examples(limit):
    rows = [r for r in load_dataset("grammarly/coedit", split="train")
            if r["task"] in TASKS and random.random() < KEEP_SHARE.get(r["task"], 1.0)]
    random.shuffle(rows)
    rows = rows[:limit * 3]
    examples = []
    # Group 3 sentences into a pseudo-paragraph; include some unchanged sentences, and some
    # paragraphs with nothing to fix at all, so the model learns to leave good writing alone.
    for i in range(0, len(rows) - 2, 3):
        sentences, suggestions = [], []
        all_clean = random.random() < CLEAN_PARAGRAPH_SHARE
        for r in rows[i:i + 3]:
            src, tgt = strip_instruction(r["src"]), r["tgt"].strip()
            category, fallback = TASKS[r["task"]]
            # Name the actual change. No word-level change (only spacing) means there's nothing to
            # teach; the first fine-tune learned to suggest "edits" that changed nothing.
            change = main_change(src, tgt)
            if all_clean or change is None or " ".join(src.split()) == " ".join(tgt.split()) or random.random() < 0.25:
                sentences.append(tgt)
                continue
            # Quoting a big rewrite as "X says the same as Y" is often false (simplification pairs
            # sometimes drop whole clauses), so large changes get the accurate general sentence.
            _, old, new = change
            # An explanation that quotes one change while the edit makes others teaches the model to
            # explain the wrong part (round 3 fixed "who's" -> "whose" but explained a comma).
            # Single change: a natural sentence about it. Several small changes: list them all.
            if change_count(src, tgt) == 1:
                reason = reason_for(category, src, tgt) if len(old) + len(new) <= 8 else None
            else:
                reason = all_changes_reason(category, src, tgt)
            reason = reason or fallback
            sentences.append(src)
            suggestions.append({"original": src, "revised": tgt, "reason": reason, "category": category})
        examples.append(example(" ".join(sentences), suggestions))
    return examples


CASUAL = Path(__file__).resolve().parent / "data-casual" / "paragraphs.jsonl"
GOALS = ["personal blog post", "college application", "personal essay", "scholarship essay", "op-ed", "not specified"]


def casual_examples(variants=3):
    """Casual paragraphs with code-planted errors: fix only the error, keep the voice.

    The voice line is measured from the paragraph itself, so the model learns to read it (every
    CoEdIT example says there are no samples, which taught it to ignore voice entirely).
    """
    if not CASUAL.exists():
        return []
    from style import describe_voice, profile_stats
    examples = []
    # Prefer the rule planted least so far. Otherwise its/it's (possible in nearly every casual
    # paragraph) crowds out rarer mistakes like whose/who's and could of.
    used = {rule[0]: 0 for rule in errors.RULES}
    # The most common real mistakes get more room. With one cap for all, round 4 caught only 73%
    # of its/it's and 17% of your/you're on the held-out test, though they're what people get wrong most.
    common = {"its-it's", "your-you're", "a-lot", "then-than", "there-their"}
    # its/it's is still the most-missed mistake on the untouched confirmation set (81%), so it
    # gets the most room of all.
    cap = lambda rule: 260 if rule == "its-it's" else 160 if rule in common else 110
    for line in open(CASUAL, encoding="utf-8-sig"):  # tolerate a BOM if the file was edited by hand
        # Straight quotes, so the error rules can see contractions like "It's".
        paragraph = json.loads(line)["paragraph"].translate(
            str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})).strip()
        voice = describe_voice(profile_stats([paragraph]))
        for _ in range(variants):
            text, suggestions = paragraph, []
            rules = [r for r in errors.applicable(paragraph) if used[r] < cap(r)]
            random.shuffle(rules)
            rules.sort(key=lambda name: used[name])  # stable: ties stay shuffled
            if rules and random.random() > CLEAN_PARAGRAPH_SHARE:
                want = 2 if random.random() < 0.45 else 1  # two-mistake paragraphs were 7/12 on the confirmation set
                # Half the two-mistake examples put both in one sentence. Round 4 had only ever seen
                # one mistake per sentence and fixed just the first ("who's job ... me and my coach").
                same_sentence = want == 2 and random.random() < 0.5
                planted_count = 0
                for rule in rules:
                    if planted_count == want:
                        break
                    within = suggestions[0]["original"] if same_sentence and suggestions else None
                    planted = errors.plant(text, rule, random, within=within)
                    if not planted:
                        continue
                    new_text, s = planted
                    if within:
                        # One suggestion fixing both: the sentence with both mistakes -> fully correct.
                        first = suggestions[0]
                        if s["revised"] != first["original"]:
                            continue
                        suggestions[0] = {"original": s["original"], "revised": first["revised"],
                                          "reason": f"{first['reason']} {s['reason']}", "category": first["category"]}
                    elif all(old["original"] not in s["original"] and s["original"] not in old["original"]
                             and old["original"] in new_text for old in suggestions):
                        suggestions.append(s)  # a different sentence, so earlier quotes stay valid
                    else:
                        continue
                    text = new_text
                    used[rule] += 1
                    planted_count += 1
            examples.append(example(text, suggestions, voice=voice, goal=random.choice(GOALS)))
    return examples


def app_examples():
    if not DB.exists():
        return []
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT f.original, f.revised, f.reason, f.category, p.stats FROM feedback f "
        "LEFT JOIN profiles p ON p.user_id = f.user_id "
        "WHERE f.accepted = 1 AND f.revised != '' AND f.category != 'generic phrasing'"
    ).fetchall()
    from style import describe_voice
    out = []
    for r in rows:
        voice = describe_voice(json.loads(r["stats"])) if r["stats"] else GENERIC_VOICE
        s = {"original": r["original"], "revised": r["revised"], "reason": r["reason"], "category": r["category"]}
        out.append(example(r["original"], [s], voice))
    return out


def main(limit=6000):
    data = coedit_examples(limit)
    casual = casual_examples()
    data += casual
    personal = app_examples()
    # Weight your group's accepted edits up; there are far fewer of them.
    data += personal * 3
    random.shuffle(data)
    split = max(1, len(data) // 20)
    OUT.mkdir(exist_ok=True)
    for name, rows in (("val", data[:split]), ("train", data[split:])):
        with open(OUT / f"{name}.jsonl", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    print(f"{len(data) - split} train / {split} val examples "
          f"({len(casual)} casual-voice, {len(personal)} from app feedback)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6000)
