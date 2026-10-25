"""Checks that a polished paragraph still says what the writer's paragraph said.

The polish rewrite (editor.polish_stream) is asked to keep every claim, example, number, name and
quotation. This compares the two versions without a model, so the writer sees a warning when
something specific went missing instead of having to spot it themselves:
- numbers ("1935", "30%", "4.0") that are in the original but not the polished text;
- names: capitalized words that aren't sentence openers ("Pacific", "Mr. Alvarez");
- quotations: text inside quotation marks;
- how many of the original's content words survive, and how much the length changed;
- whether the polished text stops short: the model ran out of room on a very long paragraph and the
  original's last sentence is gone (polish_plan.md results: one 1,137-word paragraph lost its ending).
"""
import difflib
import re

STOPWORDS = set("""a an the and or but so if then than that this these those there their they them it its it's
of to in on at by for from with as is are was were be been being have has had do does did not no
i me my we our you your he him his she her who whom which what when where why how all any some
very just also too can could would should will may might must about into over after before
because while more most such only own same other each few many much""".split())
NUMBER = re.compile(r"\d[\d,.]*%?")
QUOTE = re.compile(r"[\"“]([^\"”]{3,})[\"”]")
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
ENDS = '.!?"”’)'


def _names(text):
    """Capitalized words that don't open a sentence: a cheap stand-in for proper nouns."""
    names = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        words = WORD.findall(sentence)
        names.update(w.strip("'’") for w in words[1:] if w[0].isupper() and w.lower() not in STOPWORDS and w != "I")
    return names


def _content_words(text):
    return [w.lower().strip("'’") for w in WORD.findall(text) if len(w) > 3 and w.lower() not in STOPWORDS]


PIECE_WORDS = 250


def pieces(paragraph, limit=PIECE_WORDS):
    """The paragraph in runs of whole sentences of about `limit` words, for polishing one at a time.
    A paragraph under 1.5 x limit stays whole."""
    if len(paragraph.split()) < limit * 1.5:
        return [paragraph]
    out, current = [], []
    for sentence in SENTENCE.split(paragraph.strip()):
        if current and len(" ".join(current + [sentence]).split()) > limit:
            out.append(" ".join(current))
            current = []
        current.append(sentence)
    return out + [" ".join(current)] if current else out


def _cut_off(original, revised):
    """True if the revision stops mid-sentence, or none of the original's last sentence is near its end.
    Words match loosely, so a corrected misspelling ("impressoin" -> "impression") still counts."""
    original, revised = original.strip(), revised.strip()
    if original[-1:] in ENDS and revised[-1:] not in ENDS:
        return True
    last = _content_words(SENTENCE.split(original)[-1])
    tail = _content_words(" ".join(SENTENCE.split(revised)[-2:]))
    found = sum(1 for w in last if difflib.get_close_matches(w, tail, 1, 0.75))
    return len(last) >= 2 and found / len(last) < 0.34


def check(original, revised):
    """{"warnings": [...], "kept_words": share of the original's content words still present,
    "length_change": relative change in word count}."""
    lower_rev = revised.lower()
    missing_numbers = sorted({n.rstrip(".,") for n in NUMBER.findall(original)} - {n.rstrip(".,") for n in NUMBER.findall(revised)})
    missing_names = sorted(n for n in _names(original) if n.lower() not in lower_rev)
    missing_quotes = [q for q in QUOTE.findall(original) if q.lower() not in lower_rev]
    words = _content_words(original)
    rev_words = set(_content_words(revised))
    kept = sum(1 for w in words if w in rev_words) / len(words) if words else 1.0
    n0, n1 = len(original.split()), len(revised.split())
    change = (n1 - n0) / n0 if n0 else 0.0
    warnings = []
    if missing_numbers:
        warnings.append("A number is missing: " + ", ".join(missing_numbers))
    if missing_names:
        warnings.append("A name is missing: " + ", ".join(missing_names[:5]))
    if missing_quotes:
        warnings.append("A quotation was changed or dropped")
    if kept < 0.6:
        warnings.append(f"Much of your wording changed ({kept:.0%} of your key words kept); check it still says what you meant")
    if _cut_off(original, revised):
        warnings.append("The end of your paragraph may be missing; compare the last sentences")
    if abs(change) > 0.3:
        warnings.append(f"It's {abs(change):.0%} {'longer' if change > 0 else 'shorter'} than yours")
    return {"warnings": warnings, "kept_words": round(kept, 3), "length_change": round(change, 3)}
