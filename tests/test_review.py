import asyncio

import app as quill
import editor
from conftest import stream_events

ESSAY = "In today's fast-paced world, students uses laptops. They are everywhere.\n\nMy school gave everyone one."


def test_review_streams_instant_checks_then_each_paragraph(client, user, fake_model):
    _, h = user
    events = stream_events(client.post("/api/review", headers=h, json={"body": ESSAY}))
    assert [e["type"] for e in events] == ["instant", "start", "paragraph", "paragraph", "done"]

    instant = events[0]
    assert {s["category"] for s in instant["suggestions"]} == {"generic phrasing"}
    assert all(s["paragraph"] == 0 for s in instant["suggestions"])

    first = events[2]
    assert first["index"] == 0
    # The model's invented quote is dropped; only text that really appears in the paragraph survives.
    assert [s["original"] for s in first["suggestions"]] == ["In today's fast-paced world, students uses laptops."]
    assert events[3]["suggestions"] == []


def test_model_failure_becomes_an_error_event(client, user, monkeypatch):
    _, h = user

    async def broken(*args, **kwargs):
        raise ConnectionError("Ollama is not running")

    monkeypatch.setattr(editor, "chat", broken)
    events = stream_events(client.post("/api/review", headers=h, json={"body": "One paragraph."}))
    assert events[-1]["type"] == "error" and "Ollama is not running" in events[-1]["message"]


def test_one_review_at_a_time_per_person(client, user, fake_model):
    name, h = user
    quill.active_reviews.claim(_user_id(name))  # as if another tab's review were still running
    r = client.post("/api/review", headers=h, json={"body": ESSAY})
    assert r.status_code == 409
    assert client.post("/api/overview", headers=h, json={"body": ESSAY}).status_code == 409


def test_a_finished_review_frees_the_slot(client, user, fake_model):
    _, h = user
    assert client.post("/api/review", headers=h, json={"body": ESSAY}).status_code == 200
    assert client.post("/api/review", headers=h, json={"body": ESSAY}).status_code == 200
    assert quill.active_reviews.started == {}


def test_a_stuck_claim_expires():
    guard = quill.OneAtATime(expire_after=0)
    assert guard.claim(1) and guard.claim(1)  # zero expiry: a stale claim never blocks


def test_overview_returns_feedback(client, user, fake_model):
    _, h = user
    events = stream_events(client.post("/api/overview", headers=h, json={"body": ESSAY}))
    assert [e["type"] for e in events] == ["start", "overview", "done"]
    assert events[1]["overview"]["top_priority"] == "p"


def test_overview_says_so_when_an_essay_is_too_long_to_read_whole(client, user, fake_model, monkeypatch):
    _, h = user
    monkeypatch.setattr(editor, "CONTEXT_STEPS", (4096,))  # pretend the model can only read a little
    long_essay = "\n\n".join(f"Paragraph {i}. " + "word " * 400 for i in range(12))
    events = stream_events(client.post("/api/overview", headers=h, json={"body": long_essay}))
    notice = next(e for e in events if e["type"] == "notice")
    assert "of 12 paragraphs" in notice["message"]
    assert "Paragraph 11." not in fake_model[-1]  # the ending really was left out, and we said so


def _user_id(name):
    import db
    with db.connect() as conn:
        return conn.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()["id"]


# ---------- context sizing ----------

def test_context_grows_in_fixed_steps():
    assert editor.context_size("short") == 4096
    assert editor.context_size("x" * 15000) == 8192
    assert editor.context_size("x" * 40000) == 16384  # the longest essay the app accepts still fits
    assert editor.context_size("x" * 60000) is None


def test_fit_paragraphs_keeps_leading_paragraphs_that_fit():
    paragraphs = ["a" * 9000] * 6
    kept = editor.fit_paragraphs(paragraphs, "system prompt")
    assert 0 < len(kept) < 6 and kept == paragraphs[: len(kept)]


# ---------- fair queue ----------

def test_queue_serves_in_order_and_skips_people_who_leave():
    async def scenario():
        q = editor.FairQueue(slots=1)
        a, b, c = q.join(), q.join(), q.join()
        assert await q.try_start(a) == 0          # a gets the slot
        assert await q.try_start(b) == 1          # b is next
        assert await q.try_start(c) == 2
        await q.leave(b, started=False)           # b closes the tab while waiting
        assert await q.try_start(c) == 1          # c moves up
        await q.leave(a, started=True)            # a finishes
        assert await q.try_start(c) == 0          # c's turn
    asyncio.run(scenario())
