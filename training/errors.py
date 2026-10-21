"""Plants real, common writing errors into correct text, so the right fix is known exactly.

Used to build casual-voice training examples: the model sees a paragraph with a planted error,
and the target answer fixes only that error, leaving the writer's fragments, slang and
contractions alone. Each rule rewrites a correct pattern into the common mistake.
"""
import re

# (name, pattern matching the correct text, replacement producing the error, explanation)
# Explanations are written for the corrected text: "{right}" and "{wrong}" are the words involved.
RULES = [
    ("there-their", r"\b([Tt])here (is|was|are|were)\b", r"\1heir \2",
     "It should be “{right}”; “their” shows ownership."),
    ("its-it's", r"\b([Ii])t's\b", r"\1ts",
     "“{right}” is short for “it is”; “{wrong}” without the apostrophe means “belonging to it”."),
    ("your-you're", r"\b([Yy])ou're\b", r"\1our",
     "“{right}” means “you are”; “{wrong}” is possessive."),
    ("a-lot", r"\b([Aa]) lot\b", r"\1lot",
     "“{right}” is two words."),
    ("than-then", r"\b(more|less|better|worse|bigger|smaller|faster|slower|longer|harder|easier|rather) than\b", r"\1 then",
     "Comparisons use “than”; “then” is about time."),
    ("could-of", r"\b(could|would|should) have\b", r"\1 of",
     "It's “{right}”; “{wrong}” comes from how it sounds when spoken."),
    ("whose-who's", r"\b([Ww])hose\b", r"\1ho's",
     "“{right}” shows ownership; “{wrong}” means “who is”."),
    # "My brother and I went" -> "Me and my brother went"; keeps the capital only at a sentence start.
    ("me-and", r"\b([Mm])y (\w+) and I (went|were|had|got|spent|took|made|stayed|drove|ran)\b",
     lambda m: f"{'Me' if m.group(1) == 'M' else 'me'} and my {m.group(2)} {m.group(3)}",
     "As the subject of the sentence it's “{right}”, not “{wrong}”."),
    ("subject-verb", r"\b([Ww]e|[Tt]hey|[Yy]ou) were\b", r"\1 was",
     "With “{subject}” the verb is “were”, not “was”."),
    ("lose-loose", r"\b(lose|losing)\b", lambda m: {"lose": "loose", "losing": "loosing"}[m.group(1)],
     "“{right}” means to misplace or not win; “{wrong}” means not tight."),
]


def sentences(text):
    """Sentence spans (start, end), keeping the punctuation with each sentence."""
    return [(m.start(), m.end()) for m in re.finditer(r"[^.!?]+[.!?]+[\"')\]]*\s*|[^.!?]+$", text)]


def plant(text, rule_name, rng):
    """Plants one error of the given kind in a random eligible sentence.

    Returns (text_with_error, suggestion) or None if the rule has nowhere to apply.
    The suggestion quotes the whole erroneous sentence and restores it exactly.
    """
    name, pattern, repl, why = next(r for r in RULES if r[0] == rule_name)
    spans = [(s, e) for s, e in sentences(text) if re.search(pattern, text[s:e])]
    if not spans:
        return None
    start, end = rng.choice(spans)
    right_sentence = text[start:end].strip()
    match = re.search(pattern, right_sentence)
    wrong_sentence = right_sentence[:match.start()] + re.sub(pattern, repl, match.group(0), count=1) + right_sentence[match.end():]
    if wrong_sentence == right_sentence:
        return None
    wrong_bit = re.sub(pattern, repl, match.group(0), count=1)
    reason = why.format(right=match.group(0), wrong=wrong_bit, subject=match.group(1) if match.groups() else "")
    lead = text[start:end][: len(text[start:end]) - len(text[start:end].lstrip())]
    new_text = text[:start] + lead + wrong_sentence + text[start + len(lead) + len(right_sentence):]
    category = "word choice" if name in ("lose-loose",) else "grammar"
    return new_text, {"original": wrong_sentence, "revised": right_sentence, "reason": reason, "category": category}


def applicable(text):
    return [r[0] for r in RULES if re.search(r[1], text)]
