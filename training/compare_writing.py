"""A/B test for writing quality: runs the drafter and the line editor under named configurations
(prompt_candidates.py) on fixed inputs with fixed seeds, saves every output, and compares them.

    .venv\\Scripts\\python training\\compare_writing.py draft original      # 32 drafts, ~10 min
    .venv\\Scripts\\python training\\compare_writing.py revise original     # line edits on 40 paragraphs
    .venv\\Scripts\\python training\\compare_writing.py report original improved
    .venv\\Scripts\\python training\\compare_writing.py report original improved --human DIR

Drafts: each assignment in writing_eval/assignments.jsonl is drafted twice, once in its assigned
voice preset and once with no voice chosen, so sameness can be measured within a voice and
across voices. Revision: the paragraphs of training/eval_set.jsonl, scored for voice shift and
sameness after the edits are applied (accuracy is reliability.py's job). --human points at a
folder of .txt essays by real writers, measured the same way, as a reference rather than a target.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent


def load_app_settings():
    """The models and sampling settings from quill.env, so runs use exactly what the live app
    uses (config.py reads the environment at import). The invite code is never read."""
    env = HERE.parent / "quill.env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key.startswith("QUILL_") and key != "QUILL_PASSCODE" and key not in os.environ:
            os.environ[key] = value.strip()


load_app_settings()
sys.path.insert(0, str(HERE.parent / "backend"))
sys.path.insert(0, str(HERE))
import editor  # noqa: E402
import style  # noqa: E402
import voices  # noqa: E402
import writing_metrics as wm  # noqa: E402
from config import OLLAMA_URL  # noqa: E402
from prompt_candidates import DRAFT_CONFIGS, REVISE_CONFIGS, describe  # noqa: E402

EVAL = HERE / "writing_eval"
RUNS = EVAL / "runs"


def ask(model, system, prompt, schema, options, seed, think=None):
    body = {"model": model, "stream": False, "format": schema,
            "options": {**options, "seed": seed, "num_ctx": editor.context_size(system, prompt) or 16384},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if think is not None:
        body["think"] = think
    t = time.time()
    for attempt in range(4):  # retry server errors before recording a failure
        r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=600)
        if r.status_code < 500:
            break
        time.sleep(5 * (attempt + 1))
    r.raise_for_status()
    return editor.parse_reply(r.json()["message"]["content"]) or {}, round(time.time() - t, 1)


def save_config(name, kind):
    """The exact prompts, settings and model for a run, saved beside its outputs."""
    path = EVAL / "configs" / f"{kind}-{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(describe(name, kind), indent=2, ensure_ascii=False), encoding="utf-8")


def assignments():
    return [json.loads(line) for line in open(EVAL / "assignments.jsonl", encoding="utf-8")]


def draft(name):
    cfg = DRAFT_CONFIGS[name]
    RUNS.mkdir(parents=True, exist_ok=True)
    save_config(name, "draft")
    out = open(RUNS / f"draft-{name}.jsonl", "w", encoding="utf-8")
    jobs = [(a, a["voice"]) for a in assignments()] + [(a, None) for a in assignments()]
    for i, (a, preset) in enumerate(jobs):
        profile = {"voice_mode": "preset", "preset_id": preset} if preset else {"voice_mode": "auto", "samples": []}
        voice = voices.describe(profile, "")
        sample = voices.sample_for(profile)
        prompt = cfg["prompt"](a["instructions"], voice, sample, a["goal"], a["audience"], "", "medium")
        try:
            result, seconds = ask(editor.OVERVIEW_MODEL, cfg["system"], prompt, editor.DRAFT_SCHEMA, cfg["options"],
                                  seed=1000 + i, think=cfg.get("think"))
            error = None if result.get("paragraphs") else "no paragraphs in the reply"
        except httpx.HTTPError as exc:  # recorded, never silently skipped
            result, seconds, error = {}, 0, f"{type(exc).__name__}: {exc}"
        paras = [" ".join(q.split()) for p in result.get("paragraphs", []) if isinstance(p, str)
                 for q in re.split(r"\n\s*\n", p) if q.strip()]  # as the app does (editor.draft_stream)
        row = {"id": a["id"], "voice": preset or "none", "title": result.get("title", ""), "text": "\n\n".join(paras),
               "seconds": seconds, "error": error}
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.flush()
        print(f"  [{name}] {i + 1}/{len(jobs)} {a['id']} ({preset or 'no voice'}) {seconds}s", flush=True)


def edit_paragraph(cfg, text, goal):
    """One editor call the way the app makes it (voice measured from the text itself), with the
    app's filter. Returns (edited text, kept suggestions, seconds, error or None)."""
    voice = style.describe_voice(style.profile_stats([text]))
    prompt = cfg["prompt"](text, voice, goal)
    try:
        result, seconds = ask(editor.MODEL, cfg["system"], prompt, editor.SUGGESTION_SCHEMA, cfg["options"], seed=7)
        error = None if "suggestions" in result else "no JSON reply"
    except httpx.HTTPError as exc:
        result, seconds, error = {}, 0, f"{type(exc).__name__}: {exc}"
    kept = [s for s in result.get("suggestions", []) if isinstance(s, dict) and isinstance(s.get("original"), str)
            and s["original"] in text and s.get("revised") != s["original"]]
    applied = text
    for s in kept:
        applied = applied.replace(s["original"], s["revised"], 1)
    return applied, kept, seconds, error


def revise(name):
    """Editor on single paragraphs (training/eval_set.jsonl)."""
    cfg = REVISE_CONFIGS[name]
    RUNS.mkdir(parents=True, exist_ok=True)
    save_config(name, "revise")
    cases = [json.loads(line) for line in open(HERE / "eval_set.jsonl", encoding="utf-8")]
    out = open(RUNS / f"revise-{name}.jsonl", "w", encoding="utf-8")
    for i, c in enumerate(cases):
        applied, kept, seconds, error = edit_paragraph(cfg, c["text"], c.get("goal", ""))
        out.write(json.dumps({"id": c["id"], "before": c["text"], "after": applied, "suggestions": kept,
                              "seconds": seconds, "error": error}, ensure_ascii=False) + "\n")
        out.flush()
        print(f"  [{name}] {i + 1}/{len(cases)} {c['id']}", flush=True)


def edit_whole(cfg, text, goal):
    """Every paragraph of an essay through the editor, as "Mark it up" then accept-all would."""
    paras = wm.paragraphs(text)
    results = [edit_paragraph(cfg, p, goal) for p in paras]
    return ("\n\n".join(r[0] for r in results), sum(len(r[1]) for r in results),
            [r[3] for r in results if r[3]], [s for r in results for s in r[1]])


def pipeline(edit_name, draft_name):
    """The editor on the drafter's output: the full generate-then-revise pipeline."""
    cfg = REVISE_CONFIGS[edit_name]
    save_config(edit_name, "revise")
    rows = [r for r in load(RUNS / f"draft-{draft_name}.jsonl") if r["text"]]
    goals = {a["id"]: a["goal"] for a in assignments()}
    out = open(RUNS / f"pipeline-{draft_name}+{edit_name}.jsonl", "w", encoding="utf-8")
    for i, r in enumerate(rows):
        after, n_edits, errors, kept = edit_whole(cfg, r["text"], goals[r["id"]])
        out.write(json.dumps({"id": r["id"], "voice": r["voice"], "before": r["text"], "after": after, "edits": n_edits,
                              "suggestions": kept, "errors": errors}, ensure_ascii=False) + "\n")
        out.flush()
        print(f"  [{draft_name}+{edit_name}] {i + 1}/{len(rows)} {r['id']}", flush=True)


def human_run(edit_name, folder):
    """The editor on human-written essays you supply (.txt files). Results stay in runs/, which is
    not committed, since the essays may be private."""
    cfg = REVISE_CONFIGS[edit_name]
    out = open(RUNS / f"human+{edit_name}.jsonl", "w", encoding="utf-8")
    for p in sorted(Path(folder).glob("*.txt")):
        text = p.read_text(encoding="utf-8")
        after, n_edits, errors, kept = edit_whole(cfg, text, "")
        out.write(json.dumps({"id": p.stem, "before": text, "after": after, "edits": n_edits, "suggestions": kept,
                              "errors": errors}, ensure_ascii=False) + "\n")
        print(f"  [human+{edit_name}] {p.name}", flush=True)


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def draft_report(name):
    rows = load(RUNS / f"draft-{name}.jsonl")
    source = {a["id"]: a["instructions"] for a in assignments()}
    metrics = [wm.essay_metrics(r["text"], source[r["id"]]) for r in rows if r["text"]]
    same_none = wm.corpus_sameness([r["text"] for r in rows if r["voice"] == "none" and r["text"]])
    same_all = wm.corpus_sameness([r["text"] for r in rows if r["text"]])
    return {"summary": wm.summarize(metrics), "sameness_no_voice": same_none, "sameness_all": same_all,
            "failed": sum(bool(r.get("error")) or not r["text"] for r in rows), "seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1)}


def revise_report(name):
    rows = load(RUNS / f"revise-{name}.jsonl")
    shifts = [wm.voice_shift(r["before"], r["after"]) for r in rows]
    changed = [r for r in rows if r["after"] != r["before"]]
    avg = {k: round(sum(s[k] for s in shifts) / len(shifts), 3) for k in shifts[0]}
    before = wm.corpus_sameness([r["before"] for r in rows], n=3)
    after = wm.corpus_sameness([r["after"] for r in rows], n=3)
    reasons = [s["reason"] for r in rows for s in r["suggestions"]]
    return {"paragraphs_changed": len(changed), "edits": len(reasons),
            "distinct_reason_openings": len({" ".join(wm.words(x)[:4]) for x in reasons}),
            "voice_shift": avg,
            "sameness_before": before["shared_ngram_share"], "sameness_after": after["shared_ngram_share"]}


def stage_report():
    """What the editor does to whole essays: each pipeline and human run, before vs after editing.
    Separates the drafter's patterns (already in "before") from anything the editor adds."""
    keys = ["formulaic_openers_per_100_sentences", "stock_words_per_1000", "contractions_per_100_words",
            "sentence_mean", "sentence_cv", "mtld"]
    out = {}
    for path in sorted(RUNS.glob("pipeline-*.jsonl")) + sorted(RUNS.glob("human+*.jsonl")):
        rows = [r for r in load(path) if r["before"].strip()]
        if not rows:
            continue
        before = wm.summarize([wm.essay_metrics(r["before"]) for r in rows])
        after = wm.summarize([wm.essay_metrics(r["after"]) for r in rows])
        shifts = [wm.voice_shift(r["before"], r["after"]) for r in rows]
        words = sum(len(r["before"].split()) for r in rows)
        changed = sum(" ".join(r["before"].split()) != " ".join(r["after"].split()) for r in rows)  # ignore whitespace
        row = {"essays": len(rows), "edited_essays": changed,
               "edits_per_1000_words": round(1000 * sum(r["edits"] for r in rows) / max(1, words), 2),
               "errors": sum(len(r.get("errors", [])) for r in rows),
               "sameness_before": wm.corpus_sameness([r["before"] for r in rows])["shared_ngram_share"],
               "sameness_after": wm.corpus_sameness([r["after"] for r in rows])["shared_ngram_share"]}
        for k in keys:
            row[f"{k} (before -> after)"] = f"{before[k]} -> {after[k]}"
        row["contraction shift"] = round(sum(s["contractions_per_100_words"] for s in shifts) / len(shifts), 3)
        row["word length shift"] = round(sum(s["word_length"] for s in shifts) / len(shifts), 3)
        out[path.stem] = row
    return out


def print_stages():
    for name, row in stage_report().items():
        print(f"\n{name}")
        for metric, value in row.items():
            print(f"  {metric}: {value}")


def human_report(folder):
    texts = [p.read_text(encoding="utf-8") for p in sorted(Path(folder).glob("*.txt"))]
    metrics = [wm.essay_metrics(t) for t in texts]
    return {"summary": wm.summarize(metrics), "sameness_all": wm.corpus_sameness(texts), "essays": len(texts)}


def print_table(title, columns):
    """columns: {name: {metric: value}} -> one row per metric."""
    names = list(columns)
    metrics = [k for k in columns[names[0]] if not isinstance(columns[names[0]][k], (list, dict))]
    print(f"\n{title}")
    print("  " + "metric".ljust(38) + "".join(n.ljust(16) for n in names))
    for m in metrics:
        print("  " + m.ljust(38) + "".join(str(columns[n].get(m, "")).ljust(16) for n in names))


def report(names, human=None):
    drafts = {n: draft_report(n) for n in names if (RUNS / f"draft-{n}.jsonl").exists()}
    if human:
        drafts["human"] = human_report(human)
    if drafts:
        print_table("DRAFTS (averages per essay)", {n: {**d["summary"], "failed": d.get("failed", 0),
                                                         "seconds": d.get("seconds", "")} for n, d in drafts.items()})
        print_table("DRAFT SAMENESS (all drafts)", {n: {k: v for k, v in d["sameness_all"].items()} for n, d in drafts.items()})
        for n, d in drafts.items():
            same = d.get("sameness_no_voice", d["sameness_all"])
            print(f"\n  {n}: paragraph counts {same['paragraph_counts']}")
            print(f"  {n}: first words {same['first_sentence_openers']}")
            print(f"  {n}: shared 4-grams {same['top_shared'][:8]}")
            print(f"  {n}: openers {d['summary']['top_openers']}")
    revisions = {n: revise_report(n) for n in names if (RUNS / f"revise-{n}.jsonl").exists()}
    if revisions:
        print_table("REVISION", {n: {k: v for k, v in r.items() if k != "voice_shift"} for n, r in revisions.items()})
        print_table("REVISION VOICE SHIFT (after minus before, average)", {n: r["voice_shift"] for n, r in revisions.items()})


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    human = args[args.index("--human") + 1] if "--human" in args else None
    names = [a for a in args if a != "--human" and a != human]
    {"draft": lambda: draft(names[0]), "revise": lambda: revise(names[0]),
     "pipeline": lambda: pipeline(names[0], names[1]),   # pipeline EDIT_CONFIG DRAFT_CONFIG
     "human": lambda: human_run(names[0], names[1]),  # human EDIT_CONFIG FOLDER
     "stages": print_stages,
     "report": lambda: report(names, human)}[cmd]()
