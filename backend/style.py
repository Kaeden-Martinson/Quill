"""Voice profile statistics and generic-phrasing checks. Pure Python, no model needed."""
import re
import statistics
from collections import Counter

SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+[\"')\]]*|[^.!?]+$")
WORD_RE = re.compile(r"[A-Za-z']+")
CONTRACTION_RE = re.compile(r"\b\w+'(s|t|re|ve|ll|d|m)\b", re.I)
FIRST_PERSON = {"i", "me", "my", "mine", "myself", "we", "us", "our"}
STOPWORDS = set(
    "the a an and or but of to in on at for with by from as is are was were be been "
    "it this that these those i you he she they we me my your his her their our not "
    "so if then than there here which who what when where how why all any some no "
    "do does did have has had can could would should will just about into also more".split()
)

# Stock phrases that make writing sound generic. Flagged so the writer can say it their own way.
GENERIC_PHRASES = [
    "delve into", "delves into", "in today's fast-paced world", "in today's world",
    "in the realm of", "it is important to note", "it's important to note",
    "it is worth noting", "a testament to", "tapestry", "navigate the complexities",
    "plays a crucial role", "plays a pivotal role", "in conclusion,", "ultimately,",
    "furthermore,", "moreover,", "additionally,", "a myriad of", "multifaceted",
    "underscores the importance", "shed light on", "sheds light on", "ever-evolving",
    "game-changer", "unlock the potential", "harness the power", "at the end of the day",
    "serves as a reminder", "in an era of", "embark on a journey", "a rich tapestry",
    "the intricate", "foster a sense of", "paving the way", "stands as a",
]


def sentences(text):
    return [s.strip() for s in SENTENCE_RE.findall(text) if WORD_RE.search(s)]


def words(text):
    return [w.lower() for w in WORD_RE.findall(text)]


def profile_stats(samples):
    text = "\n\n".join(samples)
    sents = sentences(text)
    ws = words(text)
    if not sents or not ws:
        return {}
    lengths = [len(words(s)) for s in sents]
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    content = Counter(w for w in ws if w not in STOPWORDS and len(w) > 3)
    return {
        "word_count": len(ws),
        "avg_sentence_words": round(statistics.mean(lengths), 1),
        "sentence_length_spread": round(statistics.pstdev(lengths), 1),
        "short_sentence_share": round(sum(l <= 8 for l in lengths) / len(lengths), 2),
        "avg_paragraph_sentences": round(len(sents) / max(len(paragraphs), 1), 1),
        "contractions_per_100_words": round(100 * len(CONTRACTION_RE.findall(text)) / len(ws), 2),
        "first_person_per_100_words": round(100 * sum(w in FIRST_PERSON for w in ws) / len(ws), 2),
        "questions_per_100_sentences": round(100 * text.count("?") / len(sents), 1),
        "dashes_per_100_sentences": round(100 * (text.count("—") + text.count(" - ")) / len(sents), 1),
        "semicolons_per_100_sentences": round(100 * text.count(";") / len(sents), 1),
        "favorite_words": [w for w, _ in content.most_common(15)],
    }


def describe_voice(stats):
    """Turns stats into plain-English guidance for the model prompt."""
    if not stats:
        return "No writing samples yet; keep the writer's existing tone."
    lines = [
        f"Average sentence is about {stats['avg_sentence_words']} words, "
        f"with a spread of {stats['sentence_length_spread']} (mixes short and long sentences)"
        if stats["sentence_length_spread"] > 6
        else f"Average sentence is about {stats['avg_sentence_words']} words, fairly even in length",
        "Uses contractions freely" if stats["contractions_per_100_words"] > 1.5
        else "Rarely uses contractions; keep it that way",
        "Writes in first person often" if stats["first_person_per_100_words"] > 2
        else "Mostly avoids first person",
    ]
    if stats["questions_per_100_sentences"] > 4:
        lines.append("Uses rhetorical questions")
    if stats["dashes_per_100_sentences"] > 5:
        lines.append("Likes dashes for asides")
    if stats["semicolons_per_100_sentences"] > 3:
        lines.append("Uses semicolons")
    lines.append("Characteristic vocabulary: " + ", ".join(stats["favorite_words"][:10]))
    return "\n".join(f"- {l}" for l in lines)


def generic_phrase_flags(text):
    lower = text.lower()
    flags = []
    for phrase in GENERIC_PHRASES:
        start = lower.find(phrase)
        while start != -1:
            flags.append({
                "original": text[start:start + len(phrase)],
                "revised": None,
                "reason": f"\"{phrase.strip(',')}\" is a stock phrase that makes writing sound generic. "
                          "Say it the way you would, or cut it.",
                "category": "generic phrasing",
            })
            start = lower.find(phrase, start + len(phrase))
    return flags


def compare(draft, stats):
    """How far the draft drifts from the writer's usual voice."""
    if not stats:
        return []
    d = profile_stats([draft])
    if not d:
        return []
    notes = []
    if abs(d["avg_sentence_words"] - stats["avg_sentence_words"]) > 6:
        notes.append(
            f"Sentences average {d['avg_sentence_words']} words here vs. "
            f"{stats['avg_sentence_words']} in your usual writing."
        )
    if d["sentence_length_spread"] < stats["sentence_length_spread"] - 4:
        notes.append("Sentence lengths are more uniform than usual for you, so the rhythm may feel flat.")
    if stats["contractions_per_100_words"] > 1.5 and d["contractions_per_100_words"] < 0.5:
        notes.append("You normally use contractions; this draft barely does, so it may sound stiffer than you.")
    return notes
