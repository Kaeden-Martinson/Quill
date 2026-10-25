"""Pipelines B and C: texts through Quill's live editor, every suggestion applied (plan.md section 1).

    .venv\\Scripts\\python training\\generation_eval\\edit.py drafts RUN            # B: RUN/A.jsonl -> RUN/B.jsonl
    .venv\\Scripts\\python training\\generation_eval\\edit.py human SPLIT            # C: a split's human essays -> human/SPLIT-C.jsonl

Each paragraph goes through editor.review_paragraph, the app's own call (model suggestions filtered as
the app filters them, plus rules.apply's mechanical fixes), with the voice measured from the whole text
for a writer with no profile (app.writer_voice) and the goal line app.ReviewIn builds. Every
suggestion with replacement text is then applied, first occurrence each: an upper bound on editing,
since writers accept suggestions one at a time. Stock-phrase flags have no replacement and are not
applied. The editor model and settings come from quill.env (quill-editor-v7, temperature 0) and stay
fixed. Errors are recorded per paragraph; a paragraph that errors is left unchanged and counted.
"""
import asyncio
import json
import sys

import httpx

from common import CORPUS, HUMAN, read_jsonl, require_unsealed, sha256_file, write_jsonl
import generate  # loads quill.env and backend modules the same way  # noqa: F401
import editor  # noqa: E402
import voices  # noqa: E402
from config import EDIT_OPTIONS, MODEL  # noqa: E402


def goal_line(goal="", audience="", tone=""):
    """app.ReviewIn.goal_line."""
    extra = [f"{label} {value.strip()}" for label, value in (("for", audience), ("tone:", tone)) if value.strip()]
    return ", ".join([goal.strip() or "not specified", *extra])


async def edit_text(client, text, goal):
    voice = voices.describe(generate.FRESH_PROFILE, text)
    out, applied, errors = [], [], []
    for i, para in enumerate(editor.split_paragraphs(text)):
        try:
            suggestions = await editor.review_paragraph(client, para, voice, goal)
        except httpx.TransportError as exc:   # no reply at all: an outage, not an editor result
            raise SystemExit(f"Lost the Ollama server ({type(exc).__name__}); stopping without writing. "
                             "Rerun when it's back.") from None
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            errors.append({"paragraph": i, "error": f"{type(exc).__name__}: {exc}"})
            out.append(para)
            continue
        new = para
        for s in suggestions:
            if isinstance(s.get("revised"), str) and s["original"] in new:
                new = new.replace(s["original"], s["revised"], 1)
                applied.append({"paragraph": i, **s})
        out.append(new)
    return "\n\n".join(out), applied, errors


async def edit_rows(rows, goal_of):
    start = generate.environment()["ollama_version"]
    async with httpx.AsyncClient(timeout=600) as client:
        for n, r in enumerate(rows):
            now = generate.environment()["ollama_version"]
            if now != start:
                raise SystemExit(f"Ollama changed from {start} to {now} mid-run; stopping without writing.")
            after, applied, errors = await edit_text(client, r["text"], goal_of(r))
            yield {**r, "before": r["text"], "text": after, "edits_applied": applied, "edit_errors": errors,
                   "editor_model": MODEL, "editor_options": EDIT_OPTIONS}
            print(f"  {n + 1}/{len(rows)} {r.get('sample_id') or r.get('human_id')}: {len(applied)} edits"
                  f"{', ' + str(len(errors)) + ' errors' if errors else ''}", flush=True)


def drafts(run):
    a_rows = read_jsonl(CORPUS / run / "A.jsonl")
    require_unsealed(a_rows[0]["split"], f"edit.py drafts {run}")
    import prompts as P
    goals = {p["id"]: p for split in ("dev", "eval") for p in P.load(split)} if a_rows else {}
    usable = [r for r in a_rows if r["text"]]
    skipped = [{"sample_id": r["sample_id"], "reason": "no draft in pipeline A"} for r in a_rows if not r["text"]]

    async def go():
        return [row async for row in edit_rows(usable, lambda r: goal_line(goals[r["prompt_id"]].get("goal", ""),
                                                                           goals[r["prompt_id"]].get("audience", "")))]
    rows = [{**r, "pipeline": "B"} for r in asyncio.run(go())]
    write_jsonl(CORPUS / run / "B.jsonl", rows)
    record(CORPUS / run / "B-manifest.json", CORPUS / run / "B.jsonl", rows, skipped)


def human(split):
    """Every ingested human essay of one split (all sources), with no goal set, as a writer pasting
    their own essay would. Writes human/SPLIT-C.jsonl."""
    require_unsealed(split, f"edit.py human {split}")
    import human as H
    rows = H.load(split)
    if not rows:
        raise SystemExit(f"No human essays ingested for {split}.")

    async def go():
        return [row async for row in edit_rows(rows, lambda r: goal_line(""))]
    out = [{**r, "pipeline": "C"} for r in asyncio.run(go())]
    write_jsonl(HUMAN / f"{split}-C.jsonl", out)
    record(HUMAN / f"{split}-C-manifest.json", HUMAN / f"{split}-C.jsonl", out, [])


def editor_set(name):
    """Pipeline C on a fresh editor set (editor_sets.py): editor-dev, or the locked editor-holdout.
    Writes human/editor/NAME-C.jsonl."""
    if name != "editor-dev":
        require_unsealed("eval", f"edit.py editor-set {name}")
    import editor_sets
    rows = editor_sets.load(name)

    async def go():
        return [row async for row in edit_rows(rows, lambda r: goal_line(""))]
    out = [{**r, "pipeline": "C"} for r in asyncio.run(go())]
    write_jsonl(editor_sets.OUT / f"{name}-C.jsonl", out)
    record(editor_sets.OUT / f"{name}-C-manifest.json", editor_sets.OUT / f"{name}-C.jsonl", out, [])


def record(path, output, rows, skipped):
    tags = {m["name"]: m["digest"] for m in httpx.get(f"{generate.OLLAMA_URL}/api/tags", timeout=10).json()["models"]}
    path.write_text(json.dumps({
        "editor_model": MODEL, "editor_digest": tags.get(MODEL) or tags.get(f"{MODEL}:latest"),
        "editor_options": EDIT_OPTIONS, "ollama_version": generate.environment()["ollama_version"],
        "editor_py_sha256": sha256_file(generate.ROOT / "backend" / "editor.py"),
        "texts": len(rows), "edits_applied": sum(len(r["edits_applied"]) for r in rows),
        "paragraph_errors": sum(len(r["edit_errors"]) for r in rows), "skipped": skipped,
        "output_sha256": sha256_file(output)}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] == "drafts":
        drafts(sys.argv[2])
    elif sys.argv[1] == "editor-set":   # editor-set editor-dev | editor-holdout
        editor_set(sys.argv[2])
    elif sys.argv[1] == "human":
        human(sys.argv[2])
