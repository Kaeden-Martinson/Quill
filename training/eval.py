"""Scores one or more Ollama models on training/eval_set.jsonl and compares them.

    .venv\Scripts\python training\eval.py gemma4:e4b quill-editor

Metrics:
  json_ok        valid structured output
  quote_ok       suggestions that quote the paragraph exactly (unusable otherwise)
  recall         known problems (must_fix) that some suggestion fixes
  clean_edits    avg suggestions on paragraphs that were already fine (lower is better)
  invented       suggestions that add numbers not in the paragraph (should be 0)
  stock_added    suggestions that introduce stock phrases (should be 0)
  change_size    avg share of each quoted span that's rewritten (high = rewriting, not editing)
  seconds        avg time per paragraph
Raw outputs go to training/eval_results/<model>.jsonl for reading by hand.
"""
import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
from config import OLLAMA_URL  # noqa: E402
from editor import SUGGESTION_SCHEMA, SYSTEM, parse_reply  # noqa: E402
from style import GENERIC_PHRASES  # noqa: E402

NUMBER_RE = re.compile(r"\d[\d,.]*")


def ask(model, case):
    prompt = (
        f"Writer's voice:\n- {case['voice']}\n\n"
        f"Essay goal: {case['goal']}\n\n"
        f"Paragraph:\n\"\"\"\n{case['text']}\n\"\"\""
    )
    start = time.perf_counter()
    resp = httpx.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            "format": SUGGESTION_SCHEMA,
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=600,
    )
    elapsed = time.perf_counter() - start
    resp.raise_for_status()
    # Same lenient parsing the app uses, so the eval scores what users would actually see.
    reply = parse_reply(resp.json().get("message", {}).get("content", ""))
    if reply is None:
        return [], False, elapsed
    return reply.get("suggestions", []), True, elapsed


def score(model, cases):
    out_dir = HERE / "eval_results"
    out_dir.mkdir(exist_ok=True)
    totals = dict(json_ok=0, suggestions=0, quote_ok=0, must_fix=0, fixed=0, clean_cases=0,
                  clean_edits=0, invented=0, stock_added=0, change=0.0, seconds=0.0)
    with open(out_dir / f"{model.replace(':', '_').replace('/', '_')}.jsonl", "w", encoding="utf-8") as log:
        for i, case in enumerate(cases, 1):
            print(f"  [{model}] {i}/{len(cases)} {case['id']}", end="\r", flush=True)
            suggestions, ok, secs = ask(model, case)
            text = case["text"]
            totals["json_ok"] += ok
            totals["seconds"] += secs
            totals["suggestions"] += len(suggestions)
            for s in suggestions:
                orig, rev = s.get("original", ""), s.get("revised", "")
                totals["quote_ok"] += bool(orig) and orig in text
                totals["invented"] += bool(set(NUMBER_RE.findall(rev)) - set(NUMBER_RE.findall(text)))
                totals["stock_added"] += any(p in rev.lower() and p not in text.lower() for p in GENERIC_PHRASES)
                totals["change"] += 1 - SequenceMatcher(None, orig, rev).ratio()
            for problem in case["must_fix"]:
                totals["must_fix"] += 1
                totals["fixed"] += any(
                    problem.lower() in s.get("original", "").lower()
                    and problem.lower() not in s.get("revised", "").lower()
                    for s in suggestions
                )
            if case["clean"]:
                totals["clean_cases"] += 1
                totals["clean_edits"] += len(suggestions)
            log.write(json.dumps({"id": case["id"], "text": text, "suggestions": suggestions,
                                  "seconds": round(secs, 1)}, ensure_ascii=False) + "\n")
    print(" " * 60, end="\r")
    n, k = len(cases), max(totals["suggestions"], 1)
    return {
        "json_ok": f"{totals['json_ok']}/{n}",
        "quote_ok": f"{100 * totals['quote_ok'] / k:.0f}%",
        "recall": f"{totals['fixed']}/{totals['must_fix']}",
        "clean_edits": f"{totals['clean_edits'] / max(totals['clean_cases'], 1):.1f}",
        "invented": totals["invented"],
        "stock_added": totals["stock_added"],
        "change_size": f"{100 * totals['change'] / k:.0f}%",
        "seconds": f"{totals['seconds'] / n:.1f}",
    }


def main(models):
    cases = [json.loads(line) for line in open(HERE / "eval_set.jsonl", encoding="utf-8") if line.strip()]
    results = {m: score(m, cases) for m in models}
    metrics = list(next(iter(results.values())))
    width = max(len(m) for m in models) + 2
    print("metric".ljust(14) + "".join(m.ljust(width) for m in models))
    for metric in metrics:
        print(metric.ljust(14) + "".join(str(results[m][metric]).ljust(width) for m in models))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
