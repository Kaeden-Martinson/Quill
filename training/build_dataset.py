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

from reasons import reason_for

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from editor import SYSTEM  # noqa: E402  same instructions the app uses at inference

OUT = Path(__file__).resolve().parent / "data"
DB = ROOT / "data" / "quill.db"
random.seed(7)

# CoEdIT task -> (app category, reason). Paraphrase is skipped: it rewrites wholesale, which erases voice.
TASKS = {
    "gec": ("grammar", "Fixes a grammar or spelling error without changing your wording."),
    "clarity": ("clarity", "Makes the meaning easier to follow on the first read."),
    "coherence": ("flow", "Connects the ideas so the sentence reads more smoothly."),
    "simplification": ("concision", "Says the same thing in fewer, plainer words."),
    "neutralize": ("word choice", "Swaps loaded wording for something more even-handed."),
}
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
    rows = [r for r in load_dataset("grammarly/coedit", split="train") if r["task"] in TASKS]
    random.shuffle(rows)
    rows = rows[:limit * 3]
    examples = []
    # Group 3 sentences into a pseudo-paragraph; include some unchanged sentences so the model
    # learns to leave good writing alone.
    for i in range(0, len(rows) - 2, 3):
        sentences, suggestions = [], []
        for r in rows[i:i + 3]:
            src, tgt = strip_instruction(r["src"]), r["tgt"].strip()
            if src == tgt or random.random() < 0.25:
                sentences.append(tgt)
                continue
            category, fallback = TASKS[r["task"]]
            # Name the actual change; the generic sentence is only for edits we can't summarize.
            reason = reason_for(category, src, tgt) or fallback
            sentences.append(src)
            suggestions.append({"original": src, "revised": tgt, "reason": reason, "category": category})
        examples.append(example(" ".join(sentences), suggestions))
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
    personal = app_examples()
    # Weight your group's accepted edits up; there are far fewer of them.
    data += personal * 3
    random.shuffle(data)
    split = max(1, len(data) // 20)
    OUT.mkdir(exist_ok=True)
    for name, rows in (("val", data[:split]), ("train", data[split:])):
        with open(OUT / f"{name}.jsonl", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    print(f"{len(data) - split} train / {split} val examples ({len(personal)} from app feedback)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6000)
