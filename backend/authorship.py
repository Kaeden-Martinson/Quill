"""How much of an essay is still Quill's AI-written text, paragraph by paragraph.

A paragraph counts as AI-written while at least half of its words are still in the same order as
some paragraph of the AI draft. frontend/text.js (aiParagraphs) uses the same rule for the margin.
"""
import re
from difflib import SequenceMatcher

AI_SHARE = 0.5


def paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def kept_share(paragraph, ai_paragraph):
    words, ai_words = paragraph.lower().split(), ai_paragraph.lower().split()
    if not words:
        return 0.0
    kept = sum(block.size for block in SequenceMatcher(None, words, ai_words, autojunk=False).get_matching_blocks())
    return kept / len(words)


def ai_paragraph_flags(body, ai_text):
    """One True/False per paragraph of body: is it still mostly the AI draft?"""
    ai = paragraphs(ai_text)
    if not ai:
        return [False] * len(paragraphs(body))
    return [max(kept_share(p, a) for a in ai) >= AI_SHARE for p in paragraphs(body)]


def summary(body, ai_text):
    """A one-line label for the history export, or '' if nothing came from the AI."""
    flags = ai_paragraph_flags(body, ai_text)
    if not any(flags):
        return ""
    return f"{sum(flags)} of {len(flags)} paragraphs still mostly AI-written"
