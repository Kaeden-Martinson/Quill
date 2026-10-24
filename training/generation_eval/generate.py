"""Pipeline A: drafts from the production-equivalent generator, saved with full provenance (plan.md 1, 4).

    .venv\\Scripts\\python training\\generation_eval\\generate.py RUN SPLIT [--families F,F] [--limit N] [--resume]
    e.g. generate.py baseline-dev dev
         generate.py smoke dev --limit 2

The request is the app's own (editor.draft_prompt, editor.DRAFT_SYSTEM, editor.DRAFT_SCHEMA, the
model and DRAFT_OPTIONS from quill.env, num_ctx as editor.chat picks it), plus a recorded per-sample
seed: production sends none, and a seed fixes the draw without changing the sampling distribution.
The reply is post-processed exactly as editor.draft_stream does. No retries (the app has none):
errors and empty drafts are recorded, never regenerated or dropped. The one exception: a request that
got no reply because the server was down or the connection was cut is set aside (kept in
A-infrastructure.jsonl, listed in the manifest) and retried by --resume.

Writes data/generation_eval/corpus/RUN/A.jsonl (one row per sample) and RUN/manifest.json (model
digests, Ollama version, settings, prompt-file hashes, code hashes, output hash). Never overwrites;
--resume only appends samples that aren't there yet.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

import httpx

from common import CORPUS, ROOT, read_jsonl, require_unsealed, sha256_file, sha256_text, words
import prompts as P


def load_app_settings():
    """Models and sampling settings from quill.env, as the live app reads them. The invite code is never read."""
    env = ROOT / "quill.env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            key = key.strip()
            if sep and key.startswith("QUILL_") and key != "QUILL_PASSCODE" and key not in os.environ:
                os.environ[key] = value.strip()


load_app_settings()
sys.path.insert(0, str(ROOT / "backend"))
import editor  # noqa: E402
import voices  # noqa: E402
from config import DRAFT_OPTIONS, OLLAMA_URL  # noqa: E402

SAMPLES = {"quill-existing": 2, "quill-genre": 2, "persuade": 10}
FRESH_PROFILE = {"samples": [], "stats": {}, "voice_mode": "auto", "preset_id": None,
                 "custom": voices.clean_custom(None)}   # app.load_profile for a writer with no profile yet


def seed_for(sample_id):
    return int(sha256_text(sample_id)[:8], 16) % (2 ** 31)


def requested_words(length):
    return int(re.search(r"\d+", editor.DRAFT_LENGTHS.get(length, editor.DRAFT_LENGTHS["medium"])).group())


def build_request(p, seed):
    """(user prompt, request body) exactly as /api/compose builds them for a writer with no profile."""
    voice = voices.describe(FRESH_PROFILE, "")
    prompt = editor.draft_prompt(p["instructions"], voice, voices.sample_for(FRESH_PROFILE),
                                 p.get("goal", ""), p.get("audience", ""), "", p.get("length", "medium"))
    num_ctx = editor.context_size(editor.DRAFT_SYSTEM, prompt) or editor.CONTEXT_STEPS[-1]
    body = {"model": editor.OVERVIEW_MODEL,
            "messages": [{"role": "system", "content": editor.DRAFT_SYSTEM}, {"role": "user", "content": prompt}],
            "format": editor.DRAFT_SCHEMA, "stream": False,
            "options": {**DRAFT_OPTIONS, "seed": seed, "num_ctx": num_ctx}}
    return prompt, body


def postprocess(result):
    """editor.draft_stream's handling of the parsed reply: (title, body) or (None, None) for no draft."""
    paragraphs = [" ".join(q.split()) for p in (result or {}).get("paragraphs", []) if isinstance(p, str)
                  for q in re.split(r"\n\s*\n", p) if q.strip()]
    if not paragraphs:
        return None, None
    title = " ".join(((result or {}).get("title") or "").split())[:200] or "Untitled draft"
    return title, "\n\n".join(paragraphs)


def environment():
    """Model identity and engine version, recorded per run."""
    version = httpx.get(f"{OLLAMA_URL}/api/version", timeout=10).json().get("version")
    tags = {m["name"]: m["digest"] for m in httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10).json()["models"]}
    shown = subprocess.run(["ollama", "show", editor.OVERVIEW_MODEL, "--modelfile"], capture_output=True, text=True).stdout
    blobs = [line.split("blobs")[-1].strip("\\/ ") for line in shown.splitlines() if line.startswith("FROM ")]
    model = editor.OVERVIEW_MODEL
    return {"ollama_version": version, "model": model,
            "model_digest": tags.get(model) or tags.get(f"{model}:latest"), "model_blobs": blobs}


def check_engine(env):
    """Before every request: the server must answer and be the same Ollama version and model build the
    run started with. Otherwise stop, rather than mix engines in one corpus or record outages as
    generator failures (an auto-update replaced the server mid-run once)."""
    try:
        now = environment()
    except (httpx.HTTPError, ValueError) as exc:
        raise SystemExit(f"Ollama isn't answering ({type(exc).__name__}); stopping. Resume with --resume.") from None
    changed = {k: (env[k], now[k]) for k in ("ollama_version", "model_digest") if now[k] != env[k]}
    if changed:
        raise SystemExit(f"Engine changed mid-run {changed}; stopping. Start a new run name for the new engine.")


def run(name, split, families, limit=None, resume=False):
    require_unsealed(split, f"generate.py {name}")
    if not P.check():
        raise SystemExit("A locked prompt file changed; rebuild deliberately or restore it.")
    out_dir = CORPUS / name
    out = out_dir / "A.jsonl"
    if out.exists() and not resume:
        raise SystemExit(f"{out} exists; use --resume to continue it or a new run name.")
    env = environment()
    if out.exists():   # a resumed run must continue on the engine it started with
        first = read_jsonl(out)[0]
        check_engine({"ollama_version": first["ollama_version"], "model_digest": first["model_digest"]})
        set_aside_infrastructure_failures(out_dir)
    done = {r["sample_id"] for r in read_jsonl(out)} if out.exists() else set()
    jobs = [(p, k) for p in P.load(split, families) for k in range(SAMPLES[p["family"]])]
    if limit:
        jobs = jobs[:limit]
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out, "a", encoding="utf-8") as f:
        for i, (p, k) in enumerate(jobs):
            sample_id = f"{p['id']}#s{k}"
            if sample_id in done:
                continue
            check_engine(env)
            seed = seed_for(sample_id)
            prompt, body = build_request(p, seed)
            started, raw, meta, error, result = time.time(), None, {}, None, None
            try:
                resp = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=600)
                resp.raise_for_status()
                reply = resp.json()
                raw = reply.get("message", {}).get("content")
                meta = {k2: reply.get(k2) for k2 in ("done_reason", "eval_count", "prompt_eval_count", "total_duration")}
                result = editor.parse_reply(raw) if raw is not None else None
            except (httpx.HTTPError, ValueError) as exc:
                error = f"{type(exc).__name__}: {exc}"
            title, text = postprocess(result)
            if error is None and text is None:
                error = "no draft (the app shows: The model didn't return a draft)"
            row = {"sample_id": sample_id, "prompt_id": p["id"], "family": p["family"], "genre": p["genre"],
                   "split": split, "sample_index": k, "pipeline": "A",
                   "system_prompt_sha256": sha256_text(editor.DRAFT_SYSTEM), "user_prompt": prompt,
                   "options": body["options"], "seed": seed, **env,
                   "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
                   "seconds": round(time.time() - started, 1), "requested_length": p.get("length", "medium"),
                   "requested_words": requested_words(p.get("length", "medium")),
                   "title": title, "text": text, "actual_words": words(text) if text else 0,
                   "raw_reply": raw, **meta, "truncated": meta.get("done_reason") == "length",
                   "retries": 0, "postprocessing": "editor.draft_stream: whitespace collapsed, paragraphs split, title trimmed",
                   "error": error}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"  [{name}] {i + 1}/{len(jobs)} {sample_id} {row['actual_words']} words "
                  f"{row['seconds']}s{' ERROR ' + error if error else ''}", flush=True)
    write_manifest(out_dir, split, families, env)


# No reply ever came back: the server was down or the connection was cut (e.g. the PC signed out).
# These say nothing about the generator, so --resume retries them. Timeouts, HTTP errors and empty
# drafts are the generator's own failures and stay recorded.
INFRASTRUCTURE_ERRORS = ("ConnectError", "ReadError", "WriteError", "RemoteProtocolError")


def set_aside_infrastructure_failures(out_dir):
    """Moves rows that failed for infrastructure reasons, verbatim, from A.jsonl to
    A-infrastructure.jsonl (appended, never overwritten) so --resume generates them again. Every
    other line of A.jsonl is kept byte for byte."""
    out = out_dir / "A.jsonl"
    keep, moved = [], []
    for line in out.read_text(encoding="utf-8").splitlines(keepends=True):
        if not line.strip():
            continue
        if not line.endswith("\n"):
            raise SystemExit(f"{out}: the last line is incomplete (interrupted mid-write); inspect it before resuming.")
        error = json.loads(line).get("error") or ""
        (moved if error.split(":")[0] in INFRASTRUCTURE_ERRORS else keep).append(line)
    if moved:
        with open(out_dir / "A-infrastructure.jsonl", "a", encoding="utf-8") as f:
            f.writelines(moved)
        out.write_text("".join(keep), encoding="utf-8")
        print(f"set aside {len(moved)} infrastructure failure(s) to A-infrastructure.jsonl; they will be retried")


def write_manifest(out_dir, split, families, env):
    rows = read_jsonl(out_dir / "A.jsonl")
    code = {rel: sha256_file(ROOT / rel) for rel in ("backend/editor.py", "backend/config.py", "backend/voices.py",
                                                       "training/generation_eval/generate.py")}
    prompt_files = {str(p.relative_to(ROOT)).replace("\\", "/"): sha256_file(p)
                    for p in (P.PROMPTS / f"quill-{split}.jsonl", P.LOCAL / "prompts" / f"persuade-{split}.jsonl")
                    if p.exists()}
    git = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    manifest = {"split": split, "families": list(families), "samples": len(rows),
                "errors": sum(1 for r in rows if r["error"]), "truncated": sum(1 for r in rows if r.get("truncated")),
                "infrastructure_failures_retried": [r["sample_id"] + ": " + r["error"] for r in read_jsonl(out_dir / "A-infrastructure.jsonl")]
                if (out_dir / "A-infrastructure.jsonl").exists() else [],
                "environment": env, "draft_options": DRAFT_OPTIONS, "git_head": git, "code_sha256": code,
                "prompt_files_sha256": prompt_files, "A.jsonl_sha256": sha256_file(out_dir / "A.jsonl")}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"manifest: {manifest['samples']} samples, {manifest['errors']} errors, {manifest['truncated']} truncated")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("split", choices=("dev", "eval"))
    ap.add_argument("--families", default="quill-existing,quill-genre,persuade")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    run(a.run, a.split, tuple(a.families.split(",")), a.limit, a.resume)
