"""Writes a specific, one-sentence reason for a training edit, naming the words that changed.

A fixed sentence per edit type ("Fixes a grammar error") teaches the model to give the same
vague reason every time. Quoting the actual change, with a few phrasings per type, teaches it
to explain this edit.
"""
import random
import re
from difflib import SequenceMatcher

WORD = re.compile(r"\S+")

# Each template gets {old} and {new} (quoted words) and must stay one short sentence.
TEMPLATES = {
    "grammar": {
        "replace": ["“{old}” should be “{new}” here.",
                    "Changing “{old}” to “{new}” fixes the grammar.",
                    "Use “{new}” instead of “{old}”; the original doesn't agree with the rest of the sentence."],
        "insert": ["The sentence needs “{new}” to be grammatical.",
                   "Adding “{new}” completes the sentence."],
        "delete": ["“{old}” is extra here; the sentence is correct without it.",
                   "Dropping “{old}” fixes the grammar."],
    },
    "clarity": {
        "replace": ["“{new}” says what you mean more clearly than “{old}”.",
                    "Replacing “{old}” with “{new}” removes the ambiguity."],
        "insert": ["Adding “{new}” makes it clear what you're referring to."],
        "delete": ["Cutting “{old}” makes the point easier to follow."],
    },
    "flow": {
        "replace": ["“{new}” connects this to the previous idea better than “{old}”.",
                    "Swapping “{old}” for “{new}” makes the sentence read more smoothly."],
        "insert": ["“{new}” links this idea to the one before it."],
        "delete": ["Without “{old}”, the sentence flows more naturally."],
    },
    "concision": {
        "replace": ["“{new}” says the same thing as “{old}” in fewer words.",
                    "“{old}” can be shortened to “{new}” without losing meaning."],
        "insert": ["“{new}” replaces a longer phrasing."],
        "delete": ["“{old}” repeats what the sentence already says, so it can go.",
                   "Cutting “{old}” tightens the sentence."],
    },
    "word choice": {
        "replace": ["“{old}” takes a side; “{new}” states it neutrally.",
                    "“{new}” is more even-handed than “{old}”."],
        "insert": ["“{new}” keeps the claim fair to both sides."],
        "delete": ["“{old}” adds a judgment the sentence doesn't need."],
    },
}


def _quote(words, limit=6):
    text = " ".join(words)
    return text if len(words) <= limit else " ".join(words[:limit]) + "…"


def change_count(src, tgt):
    """How many separate places the edit changes."""
    a, b = WORD.findall(src), WORD.findall(tgt)
    return sum(op[0] != "equal" for op in SequenceMatcher(None, a, b, autojunk=False).get_opcodes())


LEADS = {"grammar": "Fixes the grammar", "clarity": "Makes it clearer", "flow": "Smooths the flow",
         "concision": "Simplifies it"}


def all_changes_reason(category, src, tgt, max_changes=3, max_words=4):
    """One explanation that names every change, for edits that change several places.

    e.g. Fixes the grammar: “who's” → “whose”; adds “,” after “year”.
    Returns None if there are too many or too large changes to list accurately.
    """
    a, b = WORD.findall(src), WORD.findall(tgt)
    ops = [op for op in SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op[0] != "equal"]
    if not ops or len(ops) > max_changes or category not in LEADS:
        return None
    parts = []
    for tag, i1, i2, j1, j2 in ops:
        old, new = a[i1:i2], b[j1:j2]
        if len(old) > max_words or len(new) > max_words:
            return None
        if tag == "insert":
            parts.append(f"adds “{' '.join(new)}”")
        elif tag == "delete":
            parts.append(f"removes “{' '.join(old)}”")
        else:
            parts.append(f"“{' '.join(old)}” → “{' '.join(new)}”")
    return f"{LEADS[category]}: {'; '.join(parts)}."


def main_change(src, tgt):
    """The largest changed span between two sentences: (kind, old words, new words)."""
    a, b = WORD.findall(src), WORD.findall(tgt)
    ops = [op for op in SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op[0] != "equal"]
    if not ops:
        return None
    tag, i1, i2, j1, j2 = max(ops, key=lambda op: (op[2] - op[1]) + (op[4] - op[3]))
    return tag, a[i1:i2], b[j1:j2]


def reason_for(category, src, tgt, rng=random):
    change = main_change(src, tgt)
    templates = TEMPLATES.get(category)
    if not change or not templates:
        return None
    kind, old, new = change
    if category == "concision" and (len(new) >= len(old) or len(WORD.findall(tgt)) >= len(WORD.findall(src))):
        return None  # "fewer words" would be false; the caller falls back to a general sentence
    options = templates.get(kind) or templates["replace"]
    return rng.choice(options).format(old=_quote(old), new=_quote(new))
