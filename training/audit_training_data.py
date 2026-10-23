"""Audits the line editor's training data for things that can homogenize its style:
duplication, uniform targets, formalizing edits, templated reasons, and the voice line.

    .venv\\Scripts\\python training\\audit_training_data.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import writing_metrics as wm  # noqa: E402

rows = [json.loads(line) for line in open(HERE / "data" / "train.jsonl", encoding="utf-8")]
users = [r["messages"][1]["content"] for r in rows]
paras = [u.split('Paragraph:\n"""\n', 1)[1].rsplit('\n"""', 1)[0] for u in users]
voices = [u.split("\n\nEssay goal")[0] for u in users]
edits = [s for r in rows for s in json.loads(r["messages"][2]["content"])["suggestions"]]

print(f"examples {len(rows)}; distinct paragraphs {len(set(paras))} "
      f"({100 * (1 - len(set(paras)) / len(paras)):.1f}% repeats)")
base = Counter(re.sub(r"\W+", " ", p.lower())[:80] for p in paras)
print(f"paragraphs sharing their first 80 characters with another: {sum(c for c in base.values() if c > 1)}")
generic = sum("No writing samples yet" in v for v in voices)
print(f"voice line is the generic 'no samples' text in {generic} ({100 * generic / len(rows):.0f}%)")
print(f"examples with no edits {sum(not json.loads(r['messages'][2]['content'])['suggestions'] for r in rows)}")

# Do the targets formalize? Average style change from original to revised over all edits.
shifts = [wm.voice_shift(e["original"], e["revised"]) for e in edits]
avg = {k: round(sum(s[k] for s in shifts) / len(shifts), 3) for k in shifts[0]}
print(f"\n{len(edits)} edits; average style shift of the targets (revised minus original): {avg}")
lost = sum(s["contractions_per_100_words"] < 0 for s in shifts)
print(f"edits that remove contractions: {lost} ({100 * lost / len(edits):.1f}%)")

# One-word swaps where the new word is much longer: the "upgrade the vocabulary" pattern.
swaps = Counter()
for e in edits:
    a, b = wm.words(e["original"]), wm.words(e["revised"])
    if len(a) == len(b):
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        if len(diff) == 1 and len(diff[0][1]) - len(diff[0][0]) >= 3:
            swaps[diff[0]] += 1
print(f"single-word swaps to a word 3+ letters longer: {sum(swaps.values())}; e.g. {swaps.most_common(10)}")

# How varied are the reasons? Templated reasons teach the model one way to explain everything.
openings = Counter(" ".join(wm.words(e["reason"])[:5]) for e in edits)
print(f"\nreasons: {len(edits)}; distinct 5-word openings {len(openings)}; top 6 cover "
      f"{100 * sum(c for _, c in openings.most_common(6)) / len(edits):.0f}%: {openings.most_common(6)}")
cats = Counter(e["category"] for e in edits)
print(f"categories {cats.most_common()}")

# Register of the training paragraphs: how much is casual personal writing vs encyclopedia prose.
contr = [wm.essay_metrics(p)["contractions_per_100_words"] for p in paras]
first = [100 * sum(t in {"i", "me", "my"} for t in wm.words(p)) / max(1, len(wm.words(p))) for p in paras]
print(f"\nparagraphs with any contraction {sum(c > 0 for c in contr)} ({100 * sum(c > 0 for c in contr) / len(paras):.0f}%); "
      f"with first person {sum(f > 0 for f in first)} ({100 * sum(f > 0 for f in first) / len(paras):.0f}%)")
