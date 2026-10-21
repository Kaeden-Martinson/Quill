"""Scores one or more Ollama models on training/eval_set.jsonl and compares them.

    .venv\Scripts\python training\eval.py gemma4:e4b quill-editor

Suggestions are scored the way the app shows them: ones that don't quote the paragraph exactly,
or change nothing, are dropped first (the app never displays those).

Metrics:
  json_ok        valid structured output
  dropped        suggestions the app would discard (misquoted or no change); wasted model time
  writing        known writing problems fixed (grammar, word use) out of the total
  stock          stock phrases the model itself fixed; Quill's built-in checker flags all of them anyway
  clean_edits    avg suggestions on paragraphs that were already fine (lower is better)
  reasons        share of explanations that are distinct (low = the same canned sentence repeated)
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
from style import GENERIC_PHRASES, generic_phrase_flags  # noqa: E402

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


def shown(text, suggestions):
    """Exactly the filter the app applies (editor.review_paragraph) before showing suggestions."""
    return [s for s in suggestions
            if s.get("original") and s["original"] in text and s.get("revised") != s["original"]]


def fixes(suggestions, problem):
    p = problem.lower()
    return any(p in s["original"].lower() and p not in s.get("revised", "").lower() for s in suggestions)


def score(model, cases):
    out_dir = HERE / "eval_results"
    out_dir.mkdir(exist_ok=True)
    t = dict(json_ok=0, raw=0, shown=0, writing=0, writing_total=0, stock=0, stock_total=0,
             clean_cases=0, clean_edits=0, invented=0, stock_added=0, change=0.0, seconds=0.0)
    reasons = set()
    with open(out_dir / f"{model.replace(':', '_').replace('/', '_')}.jsonl", "w", encoding="utf-8") as log:
        for i, case in enumerate(cases, 1):
            print(f"  [{model}] {i}/{len(cases)} {case['id']}", end="\r", flush=True)
            raw, ok, secs = ask(model, case)
            text = case["text"]
            visible = shown(text, raw)
            t["json_ok"] += ok
            t["seconds"] += secs
            t["raw"] += len(raw)
            t["shown"] += len(visible)
            for s in visible:
                orig, rev = s["original"], s.get("revised", "")
                reasons.add(s.get("reason", ""))
                t["invented"] += bool(set(NUMBER_RE.findall(rev)) - set(NUMBER_RE.findall(text)))
                t["stock_added"] += any(p in rev.lower() and p not in text.lower() for p in GENERIC_PHRASES)
                t["change"] += 1 - SequenceMatcher(None, orig, rev).ratio()
            # Problems the built-in stock-phrase checker flags are scored separately: users see
            # those flags whatever the model does.
            flagged = {f["original"].lower() for f in generic_phrase_flags(text)}
            for problem in case["must_fix"]:
                kind = "stock" if any(problem.lower() in f or f in problem.lower() for f in flagged) else "writing"
                t[f"{kind}_total"] += 1
                t[kind] += fixes(visible, problem)
            if case["clean"]:
                t["clean_cases"] += 1
                t["clean_edits"] += len(visible)
            log.write(json.dumps({"id": case["id"], "text": text, "suggestions": raw,
                                  "seconds": round(secs, 1)}, ensure_ascii=False) + "\n")
    print(" " * 60, end="\r")
    n, k = len(cases), max(t["shown"], 1)
    return {
        "json_ok": f"{t['json_ok']}/{n}",
        "dropped": t["raw"] - t["shown"],
        "writing": f"{t['writing']}/{t['writing_total']}",
        "stock": f"{t['stock']}/{t['stock_total']}",
        "clean_edits": f"{t['clean_edits'] / max(t['clean_cases'], 1):.1f}",
        "reasons": f"{100 * len(reasons) / k:.0f}% distinct",
        "invented": t["invented"],
        "stock_added": t["stock_added"],
        "change_size": f"{100 * t['change'] / k:.0f}%",
        "seconds": f"{t['seconds'] / n:.1f}",
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
