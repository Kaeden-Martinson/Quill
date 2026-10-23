"""Measures of writing quality and sameness, for comparing drafts and revisions.

None of these is a target on its own. They're for spotting patterns: a drafter that opens every
essay the same way, ends every one with "Ultimately", writes every paragraph the same length,
leans on the same stock words, or makes up specifics; or an editor that pulls every writer's
paragraph toward the same polished register. Compare against authentic human writing for the
same kind of assignment rather than chasing any number.
"""
import math
import re
from collections import Counter
from itertools import combinations

WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")

# Connectives that, used by reflex at the start of sentences, make prose read as a template.
FORMULAIC_OPENERS = {
    "furthermore", "moreover", "additionally", "however", "ultimately", "overall", "in conclusion",
    "in summary", "in addition", "on the other hand", "at the end of the day", "in today's",
    "in today’s", "first and foremost", "firstly", "secondly", "lastly", "finally", "consequently",
    "therefore", "thus", "in essence", "all in all", "to sum up", "while it is true",
}
# Words that stand in for a specific idea; heavy use reads as inflated or generic.
STOCK_WORDS = {
    "delve", "tapestry", "crucial", "vital", "pivotal", "foster", "navigate", "navigating", "realm",
    "landscape", "profound", "invaluable", "enhance", "journey", "testament", "underscore",
    "underscores", "embark", "resonate", "resonates", "transformative", "myriad", "seamless",
    "intricate", "nuanced", "meticulous", "multifaceted", "beacon", "cornerstone", "paramount",
    "harness", "elevate", "unwavering", "showcase", "showcases", "vibrant", "bustling",
    "indelible", "commendable", "essentially", "significantly", "ever-evolving", "dynamic",
}
CONCLUSION_OPENERS = ("in conclusion", "ultimately", "overall", "in the end", "all in all", "to sum up",
                      "in summary", "so,", "at the end of the day")
# Contractions, not possessives: "it's", "don't", "we're", but not "Maria's".
CONTRACTION = re.compile(r"\b(?:\w+n['’]t|\w+['’](?:re|ve|ll|d|m)|(?:it|that|there|here|what|who|he|she|let|where|how)['’]s)\b", re.I)
PLACEHOLDER = re.compile(r"\[[^\]]{2,80}\]")
TITLES = {"Dr", "Mr", "Ms", "Mrs", "St", "I"}


def paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def sentences(text):
    out = []
    for p in paragraphs(text):
        out += [s.strip() for s in re.findall(r"[^.!?]+(?:[.!?]+[\"'”’)\]]*|$)", p) if s.strip() and WORD.search(s)]
    return out


def words(text):
    return [w.lower().replace("’", "'") for w in WORD.findall(text)]


def cv(values):
    """Coefficient of variation: spread relative to the average (0 = all identical)."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if not mean:
        return 0.0
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) / mean


def mtld(tokens, threshold=0.72):
    """Measure of Textual Lexical Diversity (McCarthy & Jarvis, 2010), averaged both directions.
    Unlike type-token ratio it doesn't fall just because a text is longer."""
    def one_way(seq):
        factors, types, count = 0.0, set(), 0
        for tok in seq:
            count += 1
            types.add(tok)
            if len(types) / count <= threshold:
                factors += 1
                types, count = set(), 0
        if count:
            factors += (1 - len(types) / count) / (1 - threshold)
        return len(seq) / factors if factors else float(len(seq))
    if len(tokens) < 10:
        return float(len(set(tokens)))
    return (one_way(tokens) + one_way(tokens[::-1])) / 2


def opener(sentence):
    lower = sentence.lower().lstrip("\"'“‘(")
    for phrase in sorted(FORMULAIC_OPENERS, key=len, reverse=True):
        if lower.startswith(phrase):
            return phrase
    return None


def ngrams(tokens, n):
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def invented_specifics(text, source):
    """Numbers, quotations and capitalized names in text that the instructions never mentioned.
    A heuristic: it flags things for a person to check, it can't prove something is made up."""
    source_lower = source.lower()
    found = []
    for num in re.findall(r"\b\d[\d,.%]*\b", text):
        if num.strip(".,") not in source:
            found.append(num)
    # Quoted speech in double or single quotes (models often write dialogue as 'See that?').
    for quote in re.findall(r"[\"“]([^\"”]{12,})[\"”]|(?<![A-Za-z])['‘]([^'’\n]{12,}?)['’](?![A-Za-z])", text):
        quote = quote[0] or quote[1]
        if " " in quote and quote.lower() not in source_lower:
            found.append(f'"{quote[:40]}"')
    # Capitalized words mid-sentence (after a lowercase word or comma) or after a title like "Dr.".
    after = r"(?:(?<=[a-z,;] )|(?<=Dr\. )|(?<=Mr\. )|(?<=Ms\. )|(?<=Mrs\. ))"
    for name in re.findall(after + r"([A-Z][a-z]+(?: [A-Z][a-z]+)*)", text):
        if name.lower() not in source_lower and name not in TITLES:
            found.append(name)
    return found


def essay_metrics(text, source=""):
    paras = paragraphs(text)
    sents = sentences(text)
    toks = words(text)
    lengths = [len(words(s)) for s in sents]
    openers = [o for o in (opener(s) for s in sents) if o]
    first_words = Counter(words(s)[0] for s in sents if words(s))
    last = paras[-1].lower() if paras else ""
    return {
        "words": len(toks),
        "paragraphs": len(paras),
        "paragraph_cv": round(cv([len(words(p)) for p in paras]), 3),
        "sentence_mean": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "sentence_cv": round(cv(lengths), 3),
        "mtld": round(mtld(toks), 1),
        "formulaic_openers_per_100_sentences": round(100 * len(openers) / max(1, len(sents)), 1),
        "repeated_first_word_share": round(max(first_words.values()) / len(sents), 3) if sents else 0,
        "stock_words_per_1000": round(1000 * sum(t in STOCK_WORDS for t in toks) / max(1, len(toks)), 2),
        "formula_conclusion": last.startswith(CONCLUSION_OPENERS),
        "rhetorical_questions": sum(s.rstrip("\"'”’").endswith("?") for s in sents),
        "contractions_per_100_words": round(100 * len(CONTRACTION.findall(text)) / max(1, len(toks)), 2),
        "placeholders": len(PLACEHOLDER.findall(text)),
        "possible_invented": invented_specifics(text, source),
        "openers": openers,
    }


def corpus_sameness(texts, n=4, min_essays=3):
    """How much a set of essays shares wording with itself: the share of each essay's word n-grams
    that also turn up in at least `min_essays` essays of the set, plus the commonest shared ones.
    Essays on different topics by different writers share very few 4-grams; a drafter with
    stock phrasing shares many."""
    grams = [ngrams(words(t), n) for t in texts]
    seen = Counter(g for gs in grams for g in gs)
    common = {g for g, c in seen.items() if c >= min_essays}
    share = [len(gs & common) / max(1, len(gs)) for gs in grams]
    pairs = [len(a & b) / max(1, len(a | b)) for a, b in combinations(grams, 2)]
    return {
        "shared_ngram_share": round(sum(share) / max(1, len(share)), 4),
        "mean_pairwise_jaccard": round(sum(pairs) / max(1, len(pairs)), 4),
        "top_shared": [(" ".join(g), c) for g, c in seen.most_common(15) if c >= min_essays],
        "first_sentence_openers": Counter(" ".join(words(sentences(t)[0])[:3]) for t in texts if sentences(t)).most_common(5),
        "paragraph_counts": Counter(len(paragraphs(t)) for t in texts).most_common(),
    }


def summarize(rows):
    """Averages of the numeric metrics over many essays, plus rates for the yes/no ones."""
    out = {}
    keys = [k for k, v in rows[0].items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    for k in keys:
        out[k] = round(sum(r[k] for r in rows) / len(rows), 3)
    out["formula_conclusion_rate"] = round(sum(r["formula_conclusion"] for r in rows) / len(rows), 3)
    out["possible_invented_per_essay"] = round(sum(len(r["possible_invented"]) for r in rows) / len(rows), 2)
    out["top_openers"] = Counter(o for r in rows for o in r["openers"]).most_common(6)
    return out


def voice_shift(before, after):
    """How an edit moved a paragraph's style: positive numbers mean the edited text has more of it.
    An editor that keeps voice should leave these near zero apart from real fixes."""
    def stats(text):
        toks = words(text)
        sents = sentences(text)
        return {
            "contractions_per_100_words": 100 * len(CONTRACTION.findall(text)) / max(1, len(toks)),
            "sentence_mean": sum(len(words(s)) for s in sents) / max(1, len(sents)),
            "word_length": sum(len(t) for t in toks) / max(1, len(toks)),
            "stock_words_per_1000": 1000 * sum(t in STOCK_WORDS for t in toks) / max(1, len(toks)),
            "first_person_per_100_words": 100 * sum(t in {"i", "me", "my", "mine", "myself"} for t in toks) / max(1, len(toks)),
        }
    a, b = stats(before), stats(after)
    return {k: round(b[k] - a[k], 3) for k in a}
