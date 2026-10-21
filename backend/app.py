"""Quill: a voice-preserving essay editor that runs on a local model.

Run from this folder:  uvicorn app:app --host 0.0.0.0 --port 8000
"""
import json
import os
import secrets
from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import editor
import security
import style
import wordfiles
from config import FRONTEND_DIR, MODEL, PASSCODE

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


@app.post("/api/logout")
def logout(user=Depends(current_user)):
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (user["token_hash"],))
    return {"ok": True}


@app.get("/api/status")
async def status():
    return {"model": MODEL, "model_ready": await editor.model_available()}


# ---------- voice profile ----------

class ProfileIn(BaseModel):
    samples: list[str] = Field(min_length=1, max_length=10)


def load_profile(user_id):
    with db.connect() as conn:
        row = conn.execute("SELECT samples, stats FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return {"samples": [], "stats": {}}
    return {"samples": db.loads(row["samples"]), "stats": db.loads(row["stats"])}


@app.get("/api/profile")
def get_profile(user=Depends(current_user)):
    profile = load_profile(user["id"])
    return {**profile, "voice": style.describe_voice(profile["stats"])}


@app.put("/api/profile")
def put_profile(body: ProfileIn, user=Depends(current_user)):
    samples = [s.strip() for s in body.samples if s.strip()]
    stats = style.profile_stats(samples)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO profiles (user_id, samples, stats, updated) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET samples = excluded.samples, stats = excluded.stats, "
            "updated = excluded.updated",
            (user["id"], json.dumps(samples), json.dumps(stats), db.now()),
        )
    return {"samples": samples, "stats": stats, "voice": style.describe_voice(stats)}


# ---------- review ----------

class ReviewIn(BaseModel):
    body: str = Field(min_length=1, max_length=40000)
    goal: str = ""


def ndjson(first_events, model_events):
    """Streams events one JSON object per line; model failures become an error event."""
    async def gen():
        for event in first_events:
            yield json.dumps(event) + "\n"
        try:
            async for event in model_events:
                yield json.dumps(event) + "\n"
        except Exception as exc:  # Ollama down, model missing, timeout
            yield json.dumps({"type": "error", "message": f"The writing model isn't responding: {exc}"}) + "\n"
    # X-Accel-Buffering stops proxies from holding the stream until it ends.
    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/review")
async def review(body: ReviewIn, user=Depends(current_user)):
    stats = load_profile(user["id"])["stats"]
    # Instant checks go first so there's something to read while waiting for the model.
    instant = {
        "type": "instant",
        "suggestions": style.generic_phrase_flags(body.body),
        "voice_notes": style.compare(body.body, stats),
    }
    return ndjson([instant], editor.review_stream(body.body, style.describe_voice(stats), body.goal))


@app.post("/api/overview")
async def overview(body: ReviewIn, user=Depends(current_user)):
    stats = load_profile(user["id"])["stats"]
    return ndjson([], editor.overview_stream(body.body, style.describe_voice(stats), body.goal))


class FeedbackIn(BaseModel):
    original: str
    revised: str
    reason: str = ""
    category: str = ""
    accepted: bool


@app.post("/api/feedback")
def feedback(body: FeedbackIn, user=Depends(current_user)):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO feedback (user_id, original, revised, reason, category, accepted, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user["id"], body.original, body.revised, body.reason, body.category, int(body.accepted), db.now()),
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
            "SELECT id, note, created, LENGTH(body) AS chars FROM versions WHERE draft_id = ? ORDER BY created",
            (draft_id,),
        ).fetchall()
        latest = conn.execute(
            "SELECT body FROM versions WHERE draft_id = ? ORDER BY created DESC LIMIT 1", (draft_id,)
        ).fetchone()
    return {**draft, "body": latest["body"] if latest else "", "versions": [dict(v) for v in versions]}


class TitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@app.patch("/api/drafts/{draft_id}")
def rename_draft(draft_id: int, body: TitleIn, user=Depends(current_user)):
    with db.connect() as conn:
        owned_draft(conn, draft_id, user["id"])
        conn.execute("UPDATE drafts SET title = ? WHERE id = ?", (body.title, draft_id))
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
            "SELECT body, note, created FROM versions WHERE draft_id = ? ORDER BY created", (draft_id,)
        ).fetchall()
    out = [f"Writing history: {draft['title']}", f"Author: {user['name']}", f"Versions: {len(versions)}", ""]
    for i, v in enumerate(versions, 1):
        stamp = datetime.fromtimestamp(v["created"]).strftime("%Y-%m-%d %H:%M:%S")
        out += [f"===== Version {i} | {stamp} | {v['note'] or 'autosave'} =====", v["body"], ""]
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
