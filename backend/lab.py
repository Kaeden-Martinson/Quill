"""Settings lab: run one job with chosen sampling settings and report each word's candidates.

Ollama returns, for every token it wrote, that token's chance and the 10 likeliest candidates.
The reply is JSON (Quill's answer format), so the tokens are mapped back onto the text fields a
person reads, like an edit's "revised" sentence or a draft's paragraphs, and the JSON
punctuation around them is left out.
"""
import json
import math

import httpx

import editor
from config import DRAFT_OPTIONS, EDIT_OPTIONS, OLLAMA_URL

# Settings the lab can change, with the range each slider allows. 0 turns top_k and min_p off;
# 1 turns top_p off. They're always sent explicitly, so the model's own defaults never sneak in.
LIMITS = {"temperature": (0.0, 2.0), "top_p": (0.0, 1.0), "min_p": (0.0, 1.0), "top_k": (0, 200)}
CANDIDATES = 10
FIELDS = {"edit": {"original", "revised", "reason", "category"}, "draft": {"title", "paragraphs"}}
# What Ollama uses for a setting that neither Quill nor the model's Modelfile sets.
OLLAMA_DEFAULTS = {"top_p": 0.9, "top_k": 40, "min_p": 0.0}


async def effective(model, options):
    """The settings a job really runs with: Quill's own, then the model's Modelfile, then Ollama's
    defaults. The lab's presets start from these so a run there matches the live app."""
    out = dict(OLLAMA_DEFAULTS)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{OLLAMA_URL}/api/show", json={"model": model}, timeout=10)
        for line in resp.json().get("parameters", "").splitlines():
            name, _, value = line.partition(" ")
            if name in LIMITS:
                out[name] = float(value.strip().strip('"'))
    except (httpx.HTTPError, ValueError):
        pass  # Ollama is down or the model is missing: fall back to Ollama's defaults
    out.update(options)
    return clean_settings(out)


def clean_settings(settings):
    out = {}
    for name, (low, high) in LIMITS.items():
        value = settings.get(name, high if name == "top_p" else low)
        value = min(high, max(low, float(value)))
        out[name] = int(value) if name == "top_k" else round(value, 3)
    if settings.get("seed") is not None:
        out["seed"] = int(settings["seed"])
    # No slider, but Quill's drafting uses one, so its preset carries it through.
    if settings.get("repeat_penalty") is not None:
        out["repeat_penalty"] = round(min(2.0, max(1.0, float(settings["repeat_penalty"]))), 3)
    return out


def string_spans(raw):
    """Every JSON string value in raw as (start, end, key, item): character offsets of its contents,
    the key it belongs to (an array's strings take the array's key), and its index in the nearest
    enclosing array. A small scanner, since json.loads doesn't report positions."""
    spans, stack = [], []  # stack entries: {"kind": "obj"|"arr", "key": str|None, "n": int}
    expecting_key = False
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "{":
            stack.append({"kind": "obj", "key": None, "n": 0})
            expecting_key = True
        elif c == "[":
            stack.append({"kind": "arr", "key": stack[-1]["key"] if stack else None, "n": 0})
        elif c in "}]":
            if stack:
                stack.pop()
        elif c == ",":
            if stack and stack[-1]["kind"] == "obj":
                expecting_key = True
            elif stack:
                stack[-1]["n"] += 1
        elif c == ":":
            expecting_key = False
        elif c == '"':
            j = i + 1
            while j < len(raw) and raw[j] != '"':
                j += 2 if raw[j] == "\\" else 1
            if stack and stack[-1]["kind"] == "obj" and expecting_key:
                stack[-1]["key"] = raw[i + 1:j]
            else:
                key = stack[-1]["key"] if stack else None
                arrays = [s for s in stack if s["kind"] == "arr"]
                spans.append((i + 1, j, key, arrays[-1]["n"] if arrays else None))
            i = j
        i += 1
    return spans


def unescape(text):
    """Enough of JSON's escapes to read a token: \\" \\\\ \\n \\t. A token can end mid-escape."""
    try:
        return json.loads(f'"{text}"')
    except json.JSONDecodeError:
        return text.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")


def token_offsets(logprobs):
    """Character offsets of each token in the decoded reply. Tokens are bytes, and one character
    can be split across two tokens, so offsets come from decoding the bytes so far."""
    offsets, so_far = [], b""
    for t in logprobs:
        start = len(so_far.decode("utf-8", "ignore"))
        so_far += bytes(t.get("bytes") or t["token"].encode())
        offsets.append((start, len(so_far.decode("utf-8", "ignore"))))
    return offsets


def fields(raw, logprobs, wanted):
    """The readable fields of the reply, each as a list of tokens with their chances."""
    offsets = token_offsets(logprobs)
    out = []
    for start, end, key, item in string_spans(raw):
        if key not in wanted:
            continue
        tokens = []
        for (a, b), t in zip(offsets, logprobs):
            lo, hi = max(a, start), min(b, end)
            if lo >= hi:
                continue
            tokens.append({
                "text": unescape(raw[lo:hi]),
                "tok": t["token"],  # the whole token as written, to match against the candidates
                "p": round(math.exp(t["logprob"]), 5),
                "cands": [[c["token"], round(math.exp(c["logprob"]), 5)] for c in t.get("top_logprobs", [])],
            })
        out.append({"key": key, "item": item, "tokens": tokens})
    return out


async def run(mode, text, voice, sample, settings):
    """One lab run. mode "edit" reviews a paragraph with the line editor; "draft" writes a short
    draft from instructions with the drafting model. Waits its turn in the shared queue."""
    if mode == "edit":
        model, system, schema, limit = editor.MODEL, editor.SYSTEM, editor.SUGGESTION_SCHEMA, EDIT_OPTIONS["num_predict"]
        prompt = f"Writer's voice:\n{voice}\n\nEssay goal: not specified\n\nParagraph:\n\"\"\"\n{text}\n\"\"\""
    else:
        model, system, schema, limit = editor.OVERVIEW_MODEL, editor.DRAFT_SYSTEM, editor.DRAFT_SCHEMA, DRAFT_OPTIONS["num_predict"]
        prompt = editor.draft_prompt(text, voice, sample, length="short")
    options = {**settings, "num_predict": limit, "num_ctx": editor.context_size(system, prompt) or 8192}
    ticket, started = editor.queue.join(), False
    try:
        async for _ in editor.take_turn(ticket):
            pass
        started = True
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{OLLAMA_URL}/api/chat", timeout=300, json={
                "model": model, "stream": False, "format": schema, "logprobs": True, "top_logprobs": CANDIDATES,
                "options": options,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            })
        resp.raise_for_status()
        body = resp.json()
    finally:
        await editor.queue.leave(ticket, started)
    raw = body["message"]["content"]
    logprobs = body.get("logprobs") or []
    parsed = editor.parse_reply(raw) or {}
    result = {"mode": mode, "model": model, "settings": settings, "fields": fields(raw, logprobs, FIELDS[mode]),
              "tokens": len(logprobs), "seconds": round(body.get("total_duration", 0) / 1e9, 1),
              "complete": bool(parsed),
              # Ollama reports every word's chances for the line editor, but only the first for
              # gemma (the drafting model), so the page shows plain text when they're missing.
              "chances": len(logprobs) > 1}
    if mode == "edit":
        # Which suggestions the app would show (it drops quotes that aren't in the paragraph and
        # edits that change nothing). The lab leaves out Quill's grammar rules to show the model alone.
        result["suggestions"] = [
            {**s, "shown": bool(s.get("original")) and s["original"] in text and s.get("revised") != s["original"]}
            for s in parsed.get("suggestions", []) if isinstance(s, dict)
        ]
    else:
        result["title"] = parsed.get("title", "")
        result["paragraphs"] = parsed.get("paragraphs", [])
    return result
