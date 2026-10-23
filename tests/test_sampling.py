import pytest

import config
import editor
from conftest import stream_events


def test_settings_come_from_quill_env_with_defaults(monkeypatch):
    monkeypatch.setenv("QUILL_DRAFT_TEMPERATURE", "0.9")
    monkeypatch.setenv("QUILL_DRAFT_TOP_K", "50")
    monkeypatch.setenv("QUILL_DRAFT_SEED", "")  # blank means unset
    assert config.sampling("DRAFT", temperature=0.75, top_p=0.9) == {"temperature": 0.9, "top_p": 0.9, "top_k": 50}


def test_a_bad_setting_stops_startup_with_a_clear_message(monkeypatch):
    monkeypatch.setenv("QUILL_EDIT_TEMPERATURE", "warm")
    with pytest.raises(SystemExit, match="QUILL_EDIT_TEMPERATURE"):
        config.sampling("EDIT")


def test_each_job_sends_its_own_settings(client, user, monkeypatch):
    _, h = user
    sent = {}

    async def chat(client, system, prompt, schema, model=None, options=None):
        sent[system] = options
        if system == editor.DRAFT_SYSTEM:
            return {"title": "T", "paragraphs": ["One."]}
        if system == editor.OVERVIEW_SYSTEM:
            return {"strongest_part": "s", "top_priority": "p", "comments": []}
        return {"suggestions": []}

    monkeypatch.setattr(editor, "chat", chat)
    stream_events(client.post("/api/review", headers=h, json={"body": "One paragraph."}))
    stream_events(client.post("/api/overview", headers=h, json={"body": "One paragraph."}))
    stream_events(client.post("/api/compose", headers=h, json={"instructions": "Why I bike to school"}))
    # review_paragraph relies on chat's default, so check the default is the edit settings.
    assert sent[editor.SYSTEM] is None or sent[editor.SYSTEM] == config.EDIT_OPTIONS
    assert sent[editor.OVERVIEW_SYSTEM] == config.LETTER_OPTIONS
    assert sent[editor.DRAFT_SYSTEM] == config.DRAFT_OPTIONS
    assert config.DRAFT_OPTIONS["temperature"] > config.EDIT_OPTIONS["temperature"]
    # Every job has an output cap, so a stalled or runaway reply can't hold a review for minutes.
    assert all(o["num_predict"] > 0 for o in (config.EDIT_OPTIONS, config.LETTER_OPTIONS, config.DRAFT_OPTIONS))


def test_drafting_has_no_repeat_penalty_and_no_paragraph_count():
    # training/writing_eval/REPORT.md: the penalty inflated word variety; a paragraph count made every draft one shape.
    assert config.DRAFT_OPTIONS["repeat_penalty"] == 1.0
    assert not any("paragraph" in v for v in editor.DRAFT_LENGTHS.values())
    assert "Not given." in editor.draft_prompt("Why I bike", editor.NO_VOICE)


def test_the_real_chat_sends_the_settings_to_ollama(monkeypatch):
    import asyncio
    body = {}

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": '{"suggestions": []}'}}

    class Client:
        async def post(self, url, json, timeout):
            body.update(json)
            return Response()

    asyncio.run(editor.chat(Client(), "system", "prompt", {}, options={"temperature": 0.75, "top_p": 0.9}))
    assert body["options"]["temperature"] == 0.75 and body["options"]["top_p"] == 0.9
    assert "num_ctx" in body["options"]
    asyncio.run(editor.chat(Client(), "system", "prompt", {}))
    assert body["options"]["temperature"] == config.EDIT_OPTIONS["temperature"]
