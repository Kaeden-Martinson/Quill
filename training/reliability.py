"""Held-out reliability test: unseen paragraphs, planted mistakes, exact scoring.

    .venv\Scripts\python training\reliability.py build              # once: fix the test cases
    .venv\Scripts\python training\reliability.py quill-editor-v4     # score a model

The paragraphs come from training/data-heldout (different topics and styles from the training
pool, never trained on). Each case is a correct paragraph with 0, 1 or 2 mistakes planted by
code, so the right answer is known exactly. A model's suggestions are filtered the way the app
filters them, applied in order, and the result is compared word by word with the correct text.

Targets for "reliable":
  fixed       >= 90%  of planted mistakes corrected
  perfect     >= 80%  of paragraphs exactly right (every mistake fixed, nothing else changed)
  untouched   >= 95%  of clean paragraphs get no edits at all
  extra       <= 0.15 unneeded word changes per paragraph
"""
import json
import os
import random
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
sys.path.insert(0, str(HERE))
import errors  # noqa: E402
import rules  # noqa: E402
from config import OLLAMA_URL  # noqa: E402
from editor import SUGGESTION_SCHEMA, SYSTEM, parse_reply  # noqa: E402
from style import describe_voice, profile_stats  # noqa: E402

# QUILL_TESTSET=confirm scores the second, untouched set instead.
_SET = HERE / ("data-confirm" if os.environ.get("QUILL_TESTSET") == "confirm" else "data-heldout")
PARAGRAPHS = _SET / "paragraphs.jsonl"
CASES = _SET / "cases.jsonl"
TARGETS = {"fixed": 0.90, "perfect": 0.80, "untouched": 0.95, "extra": 0.15}
NO_RULES = "--no-rules" in sys.argv  # score the model alone
WORDS = re.compile(r"\S+")


def word_changes(a, b):
    """How many separate places two texts differ, word by word."""
    ops = SequenceMatcher(None, WORDS.findall(a), WORDS.findall(b), autojunk=False).get_opcodes()
    return sum(op[0] != "equal" for op in ops)


def build(seed=2026):
    rng = random.Random(seed)
    paragraphs = [json.loads(line)["paragraph"] for line in open(PARAGRAPHS, encoding="utf-8")]
    cases = []
    for i, correct in enumerate(paragraphs):
        rules = errors.applicable(correct)
        rng.shuffle(rules)
        # Paragraphs with no plantable pattern are the clean cases anyway (about half of this
        # academic-leaning set), so plantable ones mostly get one or two mistakes.
        roll = rng.random()
        want = 0 if roll < 0.10 else 1 if roll < 0.55 else 2
        text, planted = correct, []
        for rule in rules:
            if len(planted) == want:
                break
            result = None
            if planted:  # a second mistake goes in the same sentence when it can
                result = errors.plant(text, rule, rng, within=planted[-1]["wrong_sentence"])
            result = result or errors.plant(text, rule, rng)
            if result:
                text, s = result
                planted.append({"rule": rule, "wrong_sentence": s["original"], "right_sentence": s["revised"]})
        # A planted mistake counts as fixed when its sentence comes out exactly right; with two in
        # one sentence, the right sentence is the fully corrected one.
        for p in planted:
            for q in planted:
                if p is not q and p["right_sentence"] == q["wrong_sentence"]:
                    p["right_sentence"] = q["right_sentence"]
        cases.append({"id": f"h{i:03d}", "text": text, "correct": correct, "planted": planted})
    with open(CASES, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)
    counts = [len(c["planted"]) for c in cases]
    same = sum(1 for c in cases if len(c["planted"]) == 2
               and c["planted"][1]["right_sentence"] == c["planted"][0]["right_sentence"])
    print(f"{len(cases)} cases: {counts.count(0)} clean, {counts.count(1)} with one mistake, "
          f"{counts.count(2)} with two ({same} of those in the same sentence)")


def ask(client, model, text):
    # Same prompt the app sends when a writer has no saved samples: voice measured from the text.
    prompt = (f"Writer's voice:\n{describe_voice(profile_stats([text]))}\n\nEssay goal: not specified\n\n"
              f"Paragraph:\n\"\"\"\n{text}\n\"\"\"")
    r = client.post(f"{OLLAMA_URL}/api/chat", json={
        "model": model, "stream": False, "format": SUGGESTION_SCHEMA, "options": {"temperature": 0},
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
    }, timeout=600).json()
    reply = parse_reply(r.get("message", {}).get("content", "")) or {}
    # Exactly the app's filter: quotes that exist in the paragraph and actually change something.
    kept = [s for s in reply.get("suggestions", [])
            if s.get("original") and s["original"] in text and s.get("revised") not in (None, s["original"])]
    # And the app's grammar rules on top, so this measures what users actually get.
    return kept if NO_RULES else rules.apply(text, kept)


def score(model):
    cases = [json.loads(line) for line in open(CASES, encoding="utf-8")]
    t = dict(planted=0, fixed=0, perfect=0, clean=0, untouched=0, extra=0, seconds=0.0)
    out_dir = HERE / "eval_results"
    out_dir.mkdir(exist_ok=True)
    label = f"{_SET.name}-{model.replace(':', '_')}"
    with httpx.Client() as client, open(out_dir / f"{label}.jsonl", "w", encoding="utf-8") as log:
        for i, c in enumerate(cases, 1):
            print(f"  [{model}] {i}/{len(cases)}", end="\r", flush=True)
            start = time.perf_counter()
            suggestions = ask(client, model, c["text"])
            t["seconds"] += time.perf_counter() - start
            result = c["text"]
            for s in suggestions:
                result = result.replace(s["original"], s["revised"], 1)
            # A planted mistake counts as fixed when its sentence came out exactly right.
            fixed = sum(p["right_sentence"] in result for p in c["planted"])
            unfixed = len(c["planted"]) - fixed
            extra = max(0, word_changes(result, c["correct"]) - unfixed)
            t["planted"] += len(c["planted"])
            t["fixed"] += fixed
            t["perfect"] += result == c["correct"]
            t["extra"] += extra
            if not c["planted"]:
                t["clean"] += 1
                t["untouched"] += not suggestions
            log.write(json.dumps({**c, "suggestions": suggestions, "result": result, "fixed": fixed, "extra": extra},
                                 ensure_ascii=False) + "\n")
    print(" " * 50, end="\r")
    n = len(cases)
    got = {
        "fixed": t["fixed"] / max(t["planted"], 1),
        "perfect": t["perfect"] / n,
        "untouched": t["untouched"] / max(t["clean"], 1),
        "extra": t["extra"] / n,
    }
    for key, value in got.items():
        target = TARGETS[key]
        ok = value <= target if key == "extra" else value >= target
        shown = f"{value:.2f} per paragraph" if key == "extra" else f"{value:.0%}"
        bar = f"<= {target}" if key == "extra" else f">= {target:.0%}"
        print(f"  {key:10} {shown:18} target {bar:8}  {'MET' if ok else 'not yet'}")
    print(f"  {t['planted']} planted mistakes in {n} paragraphs ({t['clean']} clean); "
          f"{t['seconds'] / n:.1f}s per paragraph")
    return got


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    build() if sys.argv[1] == "build" else score(sys.argv[1])
