"""Localized suggestions: one edit per change, each labelled as a typo fix, a grammar fix or a rewrite.

The editor model quotes a phrase or sentence and returns a revised version; a sentence with three
mistakes comes back as one edit, and a "grammar" edit can also reword more than the error needs. On
110 student essays (training/generation_eval/editor_diagnosis.py) 43% of edits changed 3+ tokens;
most of those were several small fixes bundled together, and the rest reworded the writer's phrasing
("like i said" -> "as I said") under a reason saying it didn't change their wording.

Here each suggestion is split into its minimal changes, so the writer accepts or skips each one:
- typo: spelling, punctuation, capitalization or spacing;
- grammar: a word-level change of at most 2 words;
- rewrite: anything bigger, and every clarity, flow, concision, word-choice, argument or evidence
  suggestion. Rewrites are never part of "accept all" and are described as rewording.
Each piece quotes just enough of the sentence to be unique in its paragraph; pieces whose quotes
would overlap are kept together. Accepting every piece gives exactly the original suggestion's text.
"""
import difflib
import re

TOKEN = re.compile(r"\s+|\w+(?:['’]\w+)*|[^\w\s]")   # "it's" and "don't" are one word
KINDS = ("typo", "grammar", "rewrite")          # in order of how much they change
MODES = {"typos": {"typo"}, "grammar": {"typo", "grammar"}, "all": set(KINDS)}
STYLE = {"clarity", "flow", "concision", "word choice", "argument", "evidence"}
NO_WORDING_CLAIM = re.compile(r"without changing your wording", re.I)


def _words(tokens):
    return [t for t in tokens if not t.isspace()]


def hunk_kind(old, new):
    """typo / grammar / rewrite for one change, from its old and new tokens."""
    a, b = _words(old), _words(new)
    if not a and not b:
        return "typo"                                   # spacing only
    if all(not t[0].isalnum() for t in a + b):
        return "typo"                                   # punctuation only
    if len(a) == len(b) and all(p.lower() == q.lower() for p, q in zip(a, b)):
        return "typo"                                   # capitalization only
    if len(a) == 1 and len(b) == 1:
        x, y = a[0].lower(), b[0].lower()
        if sorted(x) == sorted(y) or difflib.SequenceMatcher(a=x, b=y).ratio() >= 0.75:
            return "typo"                               # one word to a similar word (or swapped letters): spelling
    return "grammar" if max(len(a), len(b)) <= 2 else "rewrite"


def _describe(old, new, kind):
    o, n = "".join(old).strip(), "".join(new).strip()
    change = f"adds “{n}”" if not o else f"removes “{o}”" if not n else f"“{o}” → “{n}”"
    if kind == "typo":
        return f"Fixes a typo or punctuation: {change}."
    if kind == "grammar":
        return f"Fixes the grammar: {change}."
    return f"Rewords part of the sentence ({change}). Check it still says what you mean, in your words."


def _rewrite_reason(reason):
    if not reason or NO_WORDING_CLAIM.search(reason):
        return "Rewords part of the sentence. Check it still says what you mean, in your words."
    return reason


def localize(paragraph, suggestion):
    """Splits one suggestion into localized ones. Returns a list (possibly just [suggestion]) of
    suggestions with a "kind". Notes without a revision ("revised" is None) pass through as rewrites."""
    original, revised = suggestion.get("original", ""), suggestion.get("revised")
    if revised is None:
        return [{**suggestion, "kind": "rewrite"}]
    a, b = TOKEN.findall(original), TOKEN.findall(revised)
    hunks = [(i1, i2, j1, j2) for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes()
             if op != "equal"]
    if not hunks:
        return []
    kinds = [hunk_kind(a[i1:i2], b[j1:j2]) for i1, i2, j1, j2 in hunks]
    if suggestion.get("category") in STYLE:
        if all(k == "typo" for k in kinds):
            # Labelled style but only fixes typos (the model once filed "freind" -> "friend" under a
            # style category with an unrelated reason): treat it as the typo fix it is.
            suggestion = {**suggestion, "category": "grammar", "reason": ""}
        else:
            return [{**suggestion, "kind": "rewrite", "reason": _rewrite_reason(suggestion.get("reason", ""))}]
    if len(hunks) == 1:
        kind = kinds[0]
        described = _describe(a[hunks[0][0]:hunks[0][1]], b[hunks[0][2]:hunks[0][3]], kind)
        if kind == "typo":
            # The model's reasons for simple typos are unreliable ("“friend” is about 17 letters long");
            # saying exactly what changed is always right.
            reason = described
        elif kind == "rewrite":
            reason = _rewrite_reason(suggestion.get("reason", ""))
        else:
            reason = suggestion.get("reason", "") or described
        return [{**suggestion, "kind": kind, "reason": reason}]

    # Context window for each hunk: grow outward a word at a time until the quoted text is unique in
    # the paragraph; windows that would overlap or touch are merged into one piece.
    def window(i1, i2):
        """Smallest token range around [i1, i2) whose text is unique in the paragraph, growing by
        one word on each side at a time (the whole quote, which is unique, if nothing smaller is)."""
        lo, hi = i1, i2
        while True:
            span = "".join(a[lo:hi]).strip()
            if span and paragraph.count(span) == 1:
                return lo, hi
            if lo == 0 and hi == len(a):
                return lo, hi
            if lo > 0:                                  # take the previous word (and its spacing)
                lo -= 1
                while lo > 0 and (a[lo].isspace() or a[lo - 1].isspace() is False and a[lo].isspace()):
                    lo -= 1
                while lo > 0 and a[lo].isspace():
                    lo -= 1
            if hi < len(a):                             # take the next word (and its spacing)
                hi += 1
                while hi < len(a) and a[hi - 1].isspace():
                    hi += 1

    groups = []
    for h, kind in zip(hunks, kinds):
        lo, hi = window(h[0], h[1])
        if groups and lo <= groups[-1]["hi"]:
            g = groups[-1]
            g["hi"] = max(g["hi"], hi)
            g["hunks"].append(h)
            g["kinds"].append(kind)
        else:
            groups.append({"lo": lo, "hi": hi, "hunks": [h], "kinds": [kind]})
    if len(groups) == 1:
        kind = max(kinds, key=KINDS.index)
        reason = suggestion.get("reason", "") if kind != "rewrite" else _rewrite_reason(suggestion.get("reason", ""))
        return [{**suggestion, "kind": kind, "reason": reason}]

    pieces = []
    for g in groups:
        out, k = [], g["lo"]
        for i1, i2, j1, j2 in g["hunks"]:
            out += a[k:i1] + b[j1:j2]
            k = i2
        out += a[k:g["hi"]]
        old_text = "".join(a[g["lo"]:g["hi"]])
        new_text = "".join(out)
        lead = len(old_text) - len(old_text.lstrip())
        trail = len(old_text) - len(old_text.rstrip())
        old_q = old_text.strip()
        new_q = new_text[lead:len(new_text) - trail] if trail else new_text[lead:]
        if not old_q or paragraph.count(old_q) != 1:
            kind = max(kinds, key=KINDS.index)          # couldn't localize safely: keep it whole
            return [{**suggestion, "kind": kind,
                     "reason": suggestion.get("reason", "") if kind != "rewrite" else _rewrite_reason(suggestion.get("reason", ""))}]
        kind = max(g["kinds"], key=KINDS.index)
        if len(g["hunks"]) == 1:
            i1, i2, j1, j2 = g["hunks"][0]
            reason = _describe(a[i1:i2], b[j1:j2], kind)
        else:
            reason = _describe(a[g["hunks"][0][0]:g["hunks"][-1][1]], b[g["hunks"][0][2]:g["hunks"][-1][3]], kind)
        pieces.append({**suggestion, "original": old_q, "revised": new_q, "reason": reason, "kind": kind})
    return pieces


def localize_all(paragraph, suggestions, mode="all"):
    """Every suggestion for a paragraph, localized, keeping only the kinds the mode shows."""
    keep = MODES.get(mode, MODES["all"])
    return [p for s in suggestions for p in localize(paragraph, s) if p["kind"] in keep]
