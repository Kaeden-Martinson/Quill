"""High-confidence grammar rules that run alongside the model.

The model misses some mechanical mistakes, especially "Its weird how..." at the start of a
sentence. Like LanguageTool-style checkers, these rules fix only patterns that are wrong in
practically every context; each was checked for false alarms on 670 correct paragraphs.
Their fixes are merged into the model's suggestion for the same sentence when there is one.
"""
import re

_ITS_NEXT = ("a|an|the|not|been|just|so|really|kind of|kinda|pretty|totally|incredibly|weird|wild|"
             "funny|crazy|okay|fine|over|always|never|still|also|only|actually|basically|probably|"
             "definitely|obvious|clear|nice|cool|strange|interesting|amazing|hard to|easy to|like|going|getting")
_YOURE_NEXT = ("gonna|not|so|welcome|still|probably|always|never|kidding|supposed|sure|ready|bored|"
               "tired|lucky|basically|definitely|literally|totally|honestly|actually")

# (pattern on the mistaken text, replacement, explanation)
RULES = [
    (re.compile(rf"\b([Ii])ts (?=(?:{_ITS_NEXT})\b)"), r"\1t's ",
     "“It's” here means “it is”; “its” without an apostrophe means “belonging to it”."),
    (re.compile(rf"\b([Yy])our (?=(?:{_YOURE_NEXT})\b)"), r"\1ou're ",
     "“You're” means “you are”; “your” is for something that belongs to you."),
    (re.compile(r"\b([Aa])lot\b"), r"\1 lot", "“A lot” is two words."),
    (re.compile(r"\b(could|would|should|must|might) of\b"), r"\1 have",
     "It's “have”, not “of”: “could of” comes from how “could've” sounds."),
    (re.compile(r"\b([Tt])heir (is|was|are|were)\b"), r"\1here \2",
     "“There” fits here; “their” is for something that belongs to them."),
]

_SENTENCE = re.compile(r"[^.!?]+[.!?]+[\"')\]]*|[^.!?]+$")


def fix_text(text):
    """Applies every rule to text. Returns (fixed_text, reasons)."""
    reasons = []
    for pattern, repl, why in RULES:
        fixed = pattern.sub(repl, text)
        if fixed != text:
            reasons.append(why)
            text = fixed
    return text, reasons


def apply(paragraph, suggestions):
    """Merges rule fixes into the model's suggestions for one paragraph.

    A sentence the model already rewrote gets the rule fix applied on top of the model's version;
    a sentence it left alone gets a suggestion of its own.
    """
    merged = []
    covered = []
    for s in suggestions:
        fixed, reasons = fix_text(s["revised"])
        if reasons:
            s = {**s, "revised": fixed, "reason": " ".join([s.get("reason", "")] + reasons).strip()}
        merged.append(s)
        covered.append(s["original"])
    for m in _SENTENCE.finditer(paragraph):
        sentence = m.group(0).strip()
        if not sentence or any(sentence in c or c in sentence for c in covered):
            continue
        fixed, reasons = fix_text(sentence)
        if reasons:
            merged.append({"original": sentence, "revised": fixed, "reason": " ".join(reasons), "category": "grammar"})
    return merged
