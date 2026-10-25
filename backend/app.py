"""Quill: a voice-preserving essay editor that runs on a local model.

Run from this folder:  uvicorn app:app --host 0.0.0.0 --port 8000
"""
import json
import os
import secrets
from datetime import datetime
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import authorship
import db
import editor
import lab
import localize
import security
import style
import voices
import wordfiles
from config import DRAFT_OPTIONS, EDIT_OPTIONS, FRONTEND_DIR, LETTER_OPTIONS, MODEL, PASSCODE

if PASSCODE == "change-me":
    print("WARNING: QUILL_PASSCODE is the default. Set it before sharing the link.")

if os.name == "nt":
    # Keep Windows from sleeping while the server runs (the screen can still turn off).
    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED; released automatically when the process exits.
    import ctypes
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)

# No public API docs: they'd advertise every endpoint to anyone with the link.
app = FastAPI(title="Quill", docs_url=None, redoc_url=None, openapi_url=None)
db.init()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
    )
    # Browsers check for a newer page and scripts on each load (a quick 304 if unchanged), so
    # people get updates without clearing their cache.
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


# ---------- auth ----------

class Register(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=8, max_length=200)
    invite: str


class Login(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    password: str = Field(max_length=200)


def start_session(conn, user_id):
    token, token_hash = security.new_token()
    conn.execute("INSERT INTO sessions (token_hash, user_id, created) VALUES (?, ?, ?)",
                 (token_hash, user_id, db.now()))
    return token


def check_rate_limit(ip, name):
    if security.by_ip.blocked(ip) or security.by_name.blocked(name.lower()):
        raise HTTPException(429, "Too many failed attempts. Wait 15 minutes and try again.")


@app.post("/api/register")
def register(body: Register, request: Request):
    ip, name = security.client_ip(request), body.name.strip()
    check_rate_limit(ip, name)
    if not secrets.compare_digest(body.invite, PASSCODE):
        security.by_ip.fail(ip)
        raise HTTPException(401, "That invite code isn't right.")
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone():
            raise HTTPException(409, "That name is taken. Sign in instead, or pick another name.")
        cur = conn.execute("INSERT INTO users (name, password_hash, created) VALUES (?, ?, ?)",
                           (name, security.hash_password(body.password), db.now()))
        token = start_session(conn, cur.lastrowid)
    return {"token": token, "name": name}


@app.post("/api/login")
def login(body: Login, request: Request):
    ip, name = security.client_ip(request), body.name.strip()
    check_rate_limit(ip, name)
    with db.connect() as conn:
        row = conn.execute("SELECT id, name, password_hash FROM users WHERE name = ?", (name,)).fetchone()
        if not row or not security.check_password(body.password, row["password_hash"]):
            security.by_ip.fail(ip)
            security.by_name.fail(name.lower())
            raise HTTPException(401, "Wrong name or password.")
        security.by_name.reset(name.lower())
        token = start_session(conn, row["id"])
    return {"token": token, "name": row["name"]}


def current_user(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    cutoff = db.now() - security.SESSION_DAYS * 86400
    with db.connect() as conn:
        row = conn.execute(
            "SELECT u.id, u.name FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.created > ?",
            (security.hash_token(token), cutoff),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Please sign in")
    return {**dict(row), "token_hash": security.hash_token(token)}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"name": user["name"]}


@app.post("/api/logout")
def logout(user=Depends(current_user)):
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (user["token_hash"],))
    return {"ok": True}


class PasswordIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(min_length=8, max_length=200)


@app.post("/api/password")
def change_password(body: PasswordIn, request: Request, user=Depends(current_user)):
    ip = security.client_ip(request)
    check_rate_limit(ip, user["name"])
    with db.connect() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not security.check_password(body.current, row["password_hash"]):
            security.by_ip.fail(ip)
            security.by_name.fail(user["name"].lower())
            raise HTTPException(401, "Your current password isn't right.")
        if body.new == body.current:
            raise HTTPException(400, "Pick a new password that's different from the current one.")
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (security.hash_password(body.new), user["id"]))
        # Keep this browser signed in; sign out everywhere else.
        others = conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                              (user["id"], user["token_hash"])).rowcount
    return {"ok": True, "signed_out": others}


@app.get("/api/status")
async def status():
    return {"model": MODEL, "model_ready": await editor.model_available()}


# ---------- voice profile ----------

VOICE_MODES = {"auto", "samples", "preset", "custom"}


class ProfileIn(BaseModel):
    # Every field is optional so the voice page can save one part at a time.
    samples: list[str] | None = Field(default=None, max_length=10)
    voice_mode: str | None = None
    preset_id: str | None = None
    custom: dict[str, str] | None = None


def load_profile(user_id):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return {"samples": [], "stats": {}, "voice_mode": "auto", "preset_id": None,
                "custom": voices.clean_custom(None)}
    return {"samples": db.loads(row["samples"]), "stats": db.loads(row["stats"]),
            "voice_mode": row["voice_mode"], "preset_id": row["preset_id"],
            "custom": voices.clean_custom(db.loads(row["custom"]))}


def profile_out(profile):
    # "voice" describes the saved samples (what the samples tab shows); "active" is what Quill uses.
    return {**profile, "voice": style.describe_voice(profile["stats"]),
            "active": voices.describe(profile, "")}


@app.get("/api/profile")
def get_profile(user=Depends(current_user)):
    return profile_out(load_profile(user["id"]))


@app.put("/api/profile")
def put_profile(body: ProfileIn, user=Depends(current_user)):
    profile = load_profile(user["id"])
    if body.samples is not None:
        profile["samples"] = [s.strip()[:20000] for s in body.samples if s.strip()]
        profile["stats"] = style.profile_stats(profile["samples"])
    if body.voice_mode is not None:
        if body.voice_mode not in VOICE_MODES:
            raise HTTPException(400, "Unknown voice choice.")
        profile["voice_mode"] = body.voice_mode
    if body.preset_id is not None:
        if body.preset_id not in voices.PRESETS:
            raise HTTPException(400, "Unknown voice preset.")
        profile["preset_id"] = body.preset_id
    if body.custom is not None:
        profile["custom"] = voices.clean_custom(body.custom)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO profiles (user_id, samples, stats, updated, voice_mode, preset_id, custom) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET samples = excluded.samples, "
            "stats = excluded.stats, updated = excluded.updated, voice_mode = excluded.voice_mode, "
            "preset_id = excluded.preset_id, custom = excluded.custom",
            (user["id"], json.dumps(profile["samples"]), json.dumps(profile["stats"]), db.now(),
             profile["voice_mode"], profile["preset_id"], json.dumps(profile["custom"])),
        )
    return profile_out(profile)


@app.get("/api/voices")
def list_voices(user=Depends(current_user)):
    presets = [{"id": k, "name": v["name"], "blurb": v["blurb"], "sample": v["sample"]}
               for k, v in voices.PRESETS.items()]
    return {"presets": presets, "custom_options": {k: list(v) for k, v in voices.CUSTOM_OPTIONS.items()}}


@app.post("/api/voice/sample-file")
async def sample_from_file(request: Request, user=Depends(current_user)):
    """Text from an uploaded Word or plain-text file, for the samples list. Nothing is stored."""
    data = await request.body()
    if len(data) > 5_000_000:
        raise HTTPException(400, "That file is too big. Try one under 5 MB.")
    if data[:2] == b"PK":  # .docx is a zip file
        try:
            _, text = wordfiles.read_docx(data)
        except wordfiles.BadFile as exc:
            raise HTTPException(400, str(exc)) from exc
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(400, "Quill can read Word (.docx) and plain-text (.txt) files.") from None
    text = text.strip()
    if not text:
        raise HTTPException(400, "That file has no text in it.")
    return {"text": text[:20000]}


def load_ignored(user_id):
    with db.connect() as conn:
        return [r["phrase"] for r in conn.execute(
            "SELECT phrase FROM ignored WHERE user_id = ? ORDER BY created", (user_id,))]


class IgnoreIn(BaseModel):
    phrase: str = Field(min_length=1, max_length=300)


@app.get("/api/ignored")
def get_ignored(user=Depends(current_user)):
    return load_ignored(user["id"])


@app.post("/api/ignored")
def add_ignored(body: IgnoreIn, user=Depends(current_user)):
    phrase = " ".join(body.phrase.split())
    with db.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO ignored (user_id, phrase, created) VALUES (?, ?, ?)",
                     (user["id"], phrase, db.now()))
    return load_ignored(user["id"])


@app.delete("/api/ignored")
def remove_ignored(phrase: str, user=Depends(current_user)):
    with db.connect() as conn:
        conn.execute("DELETE FROM ignored WHERE user_id = ? AND phrase = ?", (user["id"], " ".join(phrase.split())))
    return load_ignored(user["id"])


def not_ignored(suggestions, ignored):
    """Drops suggestions on text the writer said never to flag."""
    ignored = [p.lower() for p in ignored]
    return [s for s in suggestions if not any(p in " ".join(s.get("original", "").lower().split()) for p in ignored)]


# ---------- review ----------

class ReviewIn(BaseModel):
    body: str = Field(min_length=1, max_length=40000)
    goal: str = Field(default="", max_length=300)
    audience: str = Field(default="", max_length=100)
    tone: str = Field(default="", max_length=100)
    # How much the writer wants changed: "typos" (spelling, punctuation, capitals), "grammar" (typos
    # plus small grammar fixes) or "all" (also rewrites and style suggestions; the default, as before).
    mode: str = Field(default="all", pattern="^(typos|grammar|all)$")

    def goal_line(self):
        """Goal, audience and tone in the one "Essay goal" line the editor was trained on."""
        extra = [f"{label} {value.strip()}" for label, value in (("for", self.audience), ("tone:", self.tone))
                 if value.strip()]
        return ", ".join([self.goal.strip() or "not specified", *extra])


class OneAtATime:
    """Each person gets one review in the queue at a time, so two tabs can't take two places.

    A claim is released when its stream ends. The expiry covers a client that disconnects
    before its stream ever starts, which would otherwise never release.
    """

    def __init__(self, expire_after=30 * 60):
        self.expire_after = expire_after
        self.started = {}

    def claim(self, user_id):
        now = db.now()
        if now - self.started.get(user_id, 0) < self.expire_after:
            return False
        self.started[user_id] = now
        return True

    def release(self, user_id):
        self.started.pop(user_id, None)


active_reviews = OneAtATime()


def claim_review(user):
    if not active_reviews.claim(user["id"]):
        raise HTTPException(409, "You already have a review running, maybe in another tab. "
                                 "Wait for it to finish or stop it first.")


def ndjson(first_events, model_events, on_finish=None):
    """Streams events one JSON object per line; model failures become an error event."""
    async def gen():
        try:
            for event in first_events:
                yield json.dumps(event) + "\n"
            try:
                async for event in model_events:
                    yield json.dumps(event) + "\n"
            except Exception as exc:  # Ollama down, model missing, timeout
                yield json.dumps({"type": "error", "message": f"The writing model isn't responding: {exc}"}) + "\n"
        finally:
            if on_finish:
                on_finish()
    # X-Accel-Buffering stops proxies from holding the stream until it ends.
    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def writer_voice(profile, draft):
    """Voice guidance for the model: the writer's chosen voice, or one measured from the draft.

    The draft is the writer's own text too, and the fine-tuned editor was trained with a voice
    measured from each paragraph; "no samples yet" only ever appeared on formal examples, which
    makes it edit casual writing as if it were formal.
    """
    return voices.describe(profile, draft)


async def localized(events, paragraphs, mode):
    """Each paragraph's suggestions split into one edit per change and labelled typo, grammar or
    rewrite (localize.py), keeping the kinds the writer's mode asks for."""
    async for event in events:
        if event.get("type") == "paragraph":
            event = {**event, "suggestions": localize.localize_all(paragraphs[event["index"]], event["suggestions"], mode)}
        yield event


async def without_ignored(events, ignored):
    async for event in events:
        if event.get("type") == "paragraph":
            event = {**event, "suggestions": not_ignored(event["suggestions"], ignored)}
        yield event


@app.post("/api/review")
async def review(body: ReviewIn, user=Depends(current_user)):
    claim_review(user)
    profile, ignored = load_profile(user["id"]), load_ignored(user["id"])
    # Instant checks go first so there's something to read while waiting for the model.
    flags = [
        {**flag, "paragraph": i}
        for i, paragraph in enumerate(editor.split_paragraphs(body.body))
        for flag in style.generic_phrase_flags(paragraph)
    ]
    instant = {
        "type": "instant",
        # Stock-phrase flags are style notes, so only the "all" mode shows them.
        "suggestions": not_ignored(flags, ignored) if body.mode == "all" else [],
        "voice_notes": style.compare(body.body, profile["stats"]),
    }
    events = editor.review_stream(body.body, writer_voice(profile, body.body), body.goal_line())
    events = localized(events, editor.split_paragraphs(body.body), body.mode)
    return ndjson([instant], without_ignored(events, ignored), on_finish=lambda: active_reviews.release(user["id"]))


@app.post("/api/overview")
async def overview(body: ReviewIn, user=Depends(current_user)):
    claim_review(user)
    profile = load_profile(user["id"])
    return ndjson([], editor.overview_stream(body.body, writer_voice(profile, body.body), body.goal_line()),
                  on_finish=lambda: active_reviews.release(user["id"]))


class DraftRequest(BaseModel):
    instructions: str = Field(min_length=10, max_length=4000)
    goal: str = Field(default="", max_length=300)
    audience: str = Field(default="", max_length=100)
    tone: str = Field(default="", max_length=100)
    length: str = "medium"
    # Answers to "details only you know" (a moment, a person, how it turned out), asked before drafting
    # personal pieces.
    details: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=3)
    # The writer's own examples or evidence for an argument, explanation or letter.
    examples: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=3)


def with_details(instructions, details, examples=()):
    """The writer's own details and examples, added to their instructions in the formats tested in
    training/generation_eval: personal details (experiment E1: invented personal details 12 of 21 ->
    2 of 21, more useful and specific drafts) and examples or evidence for other pieces (E5: evidence
    +1.68, specificity +1.23, usefulness +0.57 on a 1-5 scale, fewer unsupported claims)."""
    for heading, items in (("Details I can add", details), ("Examples and evidence I can use", examples)):
        kept = [" ".join(d.split()) for d in items if d.strip()]
        if kept:
            instructions += f"\n\n{heading}:\n" + "\n".join(f"- {d}" for d in kept)
    return instructions


@app.post("/api/compose")
async def compose(body: DraftRequest, user=Depends(current_user)):
    """Drafts a new essay from instructions. It's saved as an AI-written version, and Quill keeps the
    AI text so the editor and the writing history can show which parts the writer hasn't rewritten."""
    claim_review(user)
    profile = load_profile(user["id"])
    # Without a chosen voice there's no draft to measure, so the writer's samples (if any) stand in.
    voice = voices.describe(profile, "\n\n".join(profile["samples"]))
    prompt = editor.draft_prompt(with_details(body.instructions, body.details, body.examples), voice, voices.sample_for(profile),
                                 body.goal, body.audience, body.tone, body.length)

    async def save(events):
        async for event in events:
            if event.get("type") == "draft":
                with db.connect() as conn:
                    cur = conn.execute(
                        "INSERT INTO drafts (user_id, title, created, goal, audience, tone, ai_text) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (user["id"], event["title"], db.now(), body.goal, body.audience, body.tone, event["body"]))
                    conn.execute("INSERT INTO versions (draft_id, body, note, created, source) VALUES (?, ?, ?, ?, 'ai')",
                                 (cur.lastrowid, event["body"], "Drafted by Quill AI", db.now()))
                event = {**event, "id": cur.lastrowid}
            yield event

    return ndjson([], save(editor.draft_stream(prompt)), on_finish=lambda: active_reviews.release(user["id"]))


# ---------- settings lab ----------

class LabIn(BaseModel):
    mode: str = Field(pattern="^(edit|draft)$")
    text: str = Field(min_length=1, max_length=4000)
    settings: dict[str, float | None] = {}


@app.get("/api/lab")
async def lab_defaults(user=Depends(current_user)):
    """The settings each job really runs with, so the lab can start from them."""
    return {"edit": await lab.effective(MODEL, EDIT_OPTIONS),
            "letter": await lab.effective(editor.OVERVIEW_MODEL, LETTER_OPTIONS),
            "draft": await lab.effective(editor.OVERVIEW_MODEL, DRAFT_OPTIONS),
            "limits": lab.LIMITS, "candidates": lab.CANDIDATES}


@app.post("/api/lab")
async def lab_run(body: LabIn, user=Depends(current_user)):
    """One run with the chosen settings; the live app's settings are untouched."""
    claim_review(user)
    try:
        profile = load_profile(user["id"])
        if body.mode == "edit":
            voice, sample = writer_voice(profile, body.text), None
        else:
            voice, sample = voices.describe(profile, "\n\n".join(profile["samples"])), voices.sample_for(profile)
        try:
            return await lab.run(body.mode, body.text.strip(), voice, sample, lab.clean_settings(body.settings))
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"The writing model isn't responding: {exc}") from exc
    finally:
        active_reviews.release(user["id"])


class FeedbackIn(BaseModel):
    draft_id: int
    original: str
    revised: str
    reason: str = ""
    category: str = ""
    accepted: bool


@app.post("/api/feedback")
def feedback(body: FeedbackIn, user=Depends(current_user)):
    with db.connect() as conn:
        owned_draft(conn, body.draft_id, user["id"])
        conn.execute(
            "INSERT INTO feedback (user_id, draft_id, original, revised, reason, category, accepted, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user["id"], body.draft_id, body.original, body.revised, body.reason, body.category,
             int(body.accepted), db.now()),
        )
    return {"ok": True}


# ---------- drafts and version history ----------

class DraftIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""


class VersionIn(BaseModel):
    body: str
    note: str = ""


def owned_draft(conn, draft_id, user_id):
    row = conn.execute("SELECT * FROM drafts WHERE id = ? AND user_id = ?", (draft_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "Draft not found")
    return dict(row)


@app.get("/api/drafts")
def list_drafts(user=Depends(current_user)):
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT d.id, d.title, d.created, MAX(v.created) AS updated, COUNT(v.id) AS versions "
            "FROM drafts d LEFT JOIN versions v ON v.draft_id = d.id "
            "WHERE d.user_id = ? GROUP BY d.id ORDER BY updated DESC",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/drafts")
def create_draft(body: DraftIn, user=Depends(current_user)):
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO drafts (user_id, title, created) VALUES (?, ?, ?)", (user["id"], body.title, db.now())
        )
        conn.execute(
            "INSERT INTO versions (draft_id, body, note, created) VALUES (?, ?, ?, ?)",
            (cur.lastrowid, body.body, "Started draft", db.now()),
        )
    return {"id": cur.lastrowid}


@app.get("/api/drafts/{draft_id}")
def get_draft(draft_id: int, user=Depends(current_user)):
    with db.connect() as conn:
        draft = owned_draft(conn, draft_id, user["id"])
        versions = conn.execute(
            "SELECT id, note, created, source, LENGTH(body) AS chars FROM versions WHERE draft_id = ? ORDER BY created",
            (draft_id,),
        ).fetchall()
        latest = conn.execute(
            "SELECT body FROM versions WHERE draft_id = ? ORDER BY created DESC LIMIT 1", (draft_id,)
        ).fetchone()
    return {**draft, "body": latest["body"] if latest else "", "versions": [dict(v) for v in versions]}


class DraftPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str | None = Field(default=None, max_length=300)
    audience: str | None = Field(default=None, max_length=100)
    tone: str | None = Field(default=None, max_length=100)


@app.patch("/api/drafts/{draft_id}")
def update_draft(draft_id: int, body: DraftPatch, user=Depends(current_user)):
    """Renames an essay or changes its goals; only the fields sent are changed."""
    changes = body.model_dump(exclude_none=True)
    with db.connect() as conn:
        owned_draft(conn, draft_id, user["id"])
        for column, value in changes.items():  # column names come from DraftPatch, not the request
            conn.execute(f"UPDATE drafts SET {column} = ? WHERE id = ?", (value.strip(), draft_id))
    return {"ok": True}


@app.delete("/api/drafts/{draft_id}")
def delete_draft(draft_id: int, user=Depends(current_user)):
    with db.connect() as conn:
        owned_draft(conn, draft_id, user["id"])
        conn.execute("DELETE FROM versions WHERE draft_id = ?", (draft_id,))
        conn.execute("DELETE FROM feedback WHERE draft_id = ?", (draft_id,))  # its training data too
        conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
    return {"ok": True}


@app.post("/api/drafts/{draft_id}/versions")
def save_version(draft_id: int, body: VersionIn, user=Depends(current_user)):
    with db.connect() as conn:
        owned_draft(conn, draft_id, user["id"])
        latest = conn.execute(
            "SELECT body FROM versions WHERE draft_id = ? ORDER BY created DESC LIMIT 1", (draft_id,)
        ).fetchone()
        if latest and latest["body"] == body.body:
            return {"saved": False}
        conn.execute(
            "INSERT INTO versions (draft_id, body, note, created) VALUES (?, ?, ?, ?)",
            (draft_id, body.body, body.note, db.now()),
        )
    return {"saved": True}


@app.get("/api/drafts/{draft_id}/replay")
def replay(draft_id: int, user=Depends(current_user)):
    """Every version in full, oldest first, for stepping through how the essay was written."""
    with db.connect() as conn:
        draft = owned_draft(conn, draft_id, user["id"])
        versions = conn.execute(
            "SELECT id, body, note, created, source FROM versions WHERE draft_id = ? ORDER BY created", (draft_id,)
        ).fetchall()
    return [{**dict(v), "ai_paragraphs": authorship.ai_paragraph_flags(v["body"], draft["ai_text"])} for v in versions]


@app.get("/api/versions/{version_id}")
def get_version(version_id: int, user=Depends(current_user)):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT v.* FROM versions v JOIN drafts d ON d.id = v.draft_id WHERE v.id = ? AND d.user_id = ?",
            (version_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Version not found")
    return dict(row)


@app.get("/api/drafts/{draft_id}/history.txt", response_class=PlainTextResponse)
def export_history(draft_id: int, user=Depends(current_user)):
    """Timestamped writing history, useful as evidence of authorship."""
    with db.connect() as conn:
        draft = owned_draft(conn, draft_id, user["id"])
        versions = conn.execute(
            "SELECT body, note, created, source FROM versions WHERE draft_id = ? ORDER BY created", (draft_id,)
        ).fetchall()
    out = [f"Writing history: {draft['title']}", f"Author: {user['name']}", f"Versions: {len(versions)}"]
    if draft["ai_text"]:
        out.append("This essay started from a draft written by Quill's AI; versions say how much of it remains.")
    out.append("")
    for i, v in enumerate(versions, 1):
        stamp = datetime.fromtimestamp(v["created"]).strftime("%Y-%m-%d %H:%M:%S")
        if v["source"] == "ai":
            who = "WRITTEN BY QUILL AI"
        else:
            who = authorship.summary(v["body"], draft["ai_text"]) or "written by the author"
        out += [f"===== Version {i} | {stamp} | {v['note'] or 'autosave'} | {who} =====", v["body"], ""]
    return "\n".join(out)


@app.get("/api/drafts/{draft_id}/export.docx")
def export_docx(draft_id: int, user=Depends(current_user)):
    with db.connect() as conn:
        draft = owned_draft(conn, draft_id, user["id"])
        latest = conn.execute(
            "SELECT body FROM versions WHERE draft_id = ? ORDER BY created DESC LIMIT 1", (draft_id,)
        ).fetchone()
    data = wordfiles.write_docx(draft["title"], latest["body"] if latest else "")
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.post("/api/import/docx")
async def import_docx(request: Request, user=Depends(current_user)):
    # Raw file bytes in the body; avoids a multipart parsing dependency.
    data = await request.body()
    try:
        title, body = wordfiles.read_docx(data)
    except wordfiles.BadFile as exc:
        raise HTTPException(400, str(exc)) from exc
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO drafts (user_id, title, created) VALUES (?, ?, ?)",
                           (user["id"], title or "Imported essay", db.now()))
        conn.execute("INSERT INTO versions (draft_id, body, note, created) VALUES (?, ?, ?, ?)",
                     (cur.lastrowid, body, "Imported from Word", db.now()))
    return {"id": cur.lastrowid}


# ---------- frontend ----------

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")
