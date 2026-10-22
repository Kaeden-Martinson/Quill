"""Has the local model write short, correct, casual first-person paragraphs for training data.

    .venv\Scripts\python training\make_casual.py 900

The paragraphs are the "voice" half of the casual examples: errors are planted into them later
by code (errors.py), so the correct fix is known exactly and the rest of the paragraph, with its
fragments, slang and contractions, is what the model learns to leave alone.
Writes training/data-casual/paragraphs.jsonl; rerunning continues where it stopped.
"""
import json
import random
import re
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
sys.path.insert(0, str(HERE))
from config import OLLAMA_URL  # noqa: E402
from style import generic_phrase_flags, sentences  # noqa: E402

OUT = HERE / "data-casual" / "paragraphs.jsonl"
MODEL = "gemma4:e4b"

TOPICS = [
    "a summer job", "learning to drive", "a pet that misbehaves", "a road trip", "a part-time job at a store",
    "a sibling", "a grandparent's house", "a sports team", "a failed recipe", "moving to a new town",
    "a camping trip", "a favorite teacher", "a concert", "a broken phone", "a school play", "volunteering",
    "a group project", "a first day somewhere new", "a hobby you picked up", "a holiday tradition",
    "a video game", "a long bus ride", "a garden", "learning an instrument", "a weird roommate",
    "a hiking trail", "a thrift store find", "a science fair", "getting lost", "a rainy weekend",
    "a babysitting job", "a family dinner", "a fishing trip", "a tryout", "a library", "a power outage",
]
STYLES = [
    "chatty and casual, with contractions and one short sentence fragment for effect",
    "dry and funny, with understatement and contractions",
    "warm and reflective, short sentences, one starting with And or But",
    "conversational, with a rhetorical question and contractions",
    "plain and direct, with a one-word sentence for emphasis",
    "excited and casual, with a little slang like gonna or kinda",
]
SCHEMA = {"type": "object", "properties": {"paragraph": {"type": "string"}}, "required": ["paragraph"]}
CONTRACTION = re.compile(r"\b\w+'(?:s|t|re|ve|ll|d|m)\b", re.I)
# Curly quotes would hide contractions from the error rules ("It’s" never matches "It's").
STRAIGHT = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


def normalize(p):
    return p.translate(STRAIGHT).strip()


# Constructions some error rules need but casual paragraphs rarely contain. With --need, the
# prompt asks for one and only paragraphs where that rule can fire are kept.
NEEDS = {
    "me-and": ("Somewhere, use a person and yourself together as the subject, written correctly "
               "with you last, like \"my sister and I drove\" or \"the coach and I talked\"."),
    "fewer-less": "Somewhere, use the word \"fewer\" correctly with something countable, like \"fewer people\".",
}


def prompt(rng, need=None):
    topic, style = rng.choice(TOPICS), rng.choice(STYLES)
    return (
        f"Write one paragraph (3 to 5 sentences) in first person about {topic}, the way a real "
        f"high school or college student would write it in a personal essay or blog post. "
        f"Style: {style}. Use correct spelling and grammar (sentence fragments are fine when "
        f"deliberate). No clichés, no moral at the end, no title. {NEEDS.get(need, '')}"
    ).strip()


def usable(p):
    n = len(sentences(p))
    return (2 <= n <= 6 and len(p) <= 700 and CONTRACTION.search(p)
            and not generic_phrase_flags(p) and "\n" not in p.strip())


def main(target, need=None):
    """Generates until the file holds `target` paragraphs (or, with `need`, `target` more of that kind)."""
    import errors
    OUT.parent.mkdir(exist_ok=True)
    have = sum(1 for _ in open(OUT, encoding="utf-8")) if OUT.exists() else 0
    if need:
        target += have
    rng = random.Random(have)  # different topics after a restart
    with open(OUT, "a", encoding="utf-8") as out, httpx.Client(timeout=300) as client:
        while have < target:
            r = client.post(f"{OLLAMA_URL}/api/chat", json={
                "model": MODEL, "stream": False, "format": SCHEMA,
                "messages": [{"role": "user", "content": prompt(rng, need)}],
                "options": {"temperature": 0.9},  # variety of content and phrasing across paragraphs
            }).json()
            try:
                p = normalize(json.loads(r["message"]["content"])["paragraph"])
            except (KeyError, json.JSONDecodeError):
                continue
            if usable(p) and (not need or need in errors.applicable(p)):
                out.write(json.dumps({"paragraph": p}, ensure_ascii=False) + "\n")
                out.flush()
                have += 1
                print(f"  {have}/{target}", end="\r", flush=True)
    print(f"\n{have} paragraphs in {OUT}")


if __name__ == "__main__":
    # make_casual.py 900            -> fill the file up to 900 paragraphs
    # make_casual.py 60 me-and      -> add 60 paragraphs where the me-and rule can fire
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 900, sys.argv[2] if len(sys.argv) > 2 else None)
