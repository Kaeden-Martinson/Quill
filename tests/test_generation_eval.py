"""The generator evaluation harness must match the live app, and its checks must catch what they claim to."""
import asyncio
import os
import sys
from pathlib import Path

import pytest

import editor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training" / "generation_eval"))
_env = dict(os.environ)
import generate  # noqa: E402  (reads quill.env into the environment at import)
import human  # noqa: E402
import report  # noqa: E402
import validate  # noqa: E402
os.environ.clear()
os.environ.update(_env)   # keep later tests on the test configuration

REPLIES = [
    {"title": "  A   title ", "paragraphs": ["First  para.", "Second\n\nThird", "", 7]},
    {"title": "", "paragraphs": ["Only one"]},
    {"title": "x" * 300, "paragraphs": ["a"]},
    {"paragraphs": []},
    None,
]


@pytest.mark.parametrize("reply", REPLIES)
def test_postprocess_matches_the_app(monkeypatch, reply):
    async def fake_chat(*args, **kwargs):
        return reply
    monkeypatch.setattr(editor, "chat", fake_chat)

    async def app_events():
        return [e async for e in editor.draft_stream("prompt")]
    events = asyncio.run(app_events())
    draft = next((e for e in events if e["type"] == "draft"), None)
    title, body = generate.postprocess(reply)
    if draft is None:
        assert body is None and any(e["type"] == "error" for e in events)
    else:
        assert (title, body) == (draft["title"], draft["body"])


def test_request_is_the_apps_for_a_new_writer():
    prompt, body = generate.build_request({"instructions": "Write about tides.", "goal": "article",
                                           "audience": "kids", "length": "short"}, seed=42)
    assert prompt == editor.draft_prompt("Write about tides.", editor.NO_VOICE, None, "article", "kids", "", "short")
    assert "Writer's voice:\nNot given." in prompt
    assert body["messages"][0]["content"] == editor.DRAFT_SYSTEM
    assert body["format"] == editor.DRAFT_SCHEMA
    assert body["options"]["seed"] == 42
    assert {k: v for k, v in body["options"].items() if k not in ("seed", "num_ctx")} == generate.DRAFT_OPTIONS
    assert generate.requested_words("short") == 250 and generate.requested_words("long") == 900


def test_seeds_are_stable_and_distinct():
    assert generate.seed_for("q-argument-1#s0") == generate.seed_for("q-argument-1#s0")
    assert generate.seed_for("q-argument-1#s0") != generate.seed_for("q-argument-1#s1")


def test_detector_call_uses_label_then_threshold():
    det = {"threshold": 0.5, "higher_means": "ai"}
    assert report.is_ai({"label": "human", "score": 0.99, "error": None}, det) is False
    assert report.is_ai({"label": None, "score": 0.7, "error": None}, det) is True
    assert report.is_ai({"label": None, "score": 0.7, "error": "timeout"}, det) is None
    assert report.is_ai({"label": None, "score": 0.7, "error": None}, {"threshold": None}) is None


def test_plan_flags_as_written():
    section = {"human_tier_A": {"essays": 200, "false_positive": {"rate": 0.06, "wilson95": [0.034, 0.10]},
                                "exploratory_breakdowns": {"english_learner": {"yes": {"rate": 0.15}, "no": {"rate": 0.04}}}},
               "editor_effect_Q3": {"mcnemar_p": 0.01}, "missing": {"human tier A": 50}}
    found = report.flags(section, 0.06)
    assert any("wholly above 1%" in f for f in found)
    assert any("english_learner=yes" in f for f in found)
    assert any("McNemar" in f for f in found)
    assert any("more than 20% of results missing" in f for f in found)


def test_human_text_checks():
    assert human.malformed("") == "empty"
    assert human.malformed("1234 5678 90 ## $$ %%") == "mostly non-letter characters"
    assert human.malformed("A real essay," + " " * 400 + "with long runs of spaces.") is None
    assert human.malformed("Itâ€™s broken") == "encoding damage"
    assert human.malformed("A normal sentence about school.") is None


def test_editor_micusp_students_are_excluded_by_rule():
    assert validate.editor_micusp_student("BIO.G0.01.1")      # human_corpus
    assert validate.editor_micusp_student("ENG.G2.05.1")      # sealed editor test
    assert not validate.editor_micusp_student("ENG.G2.06.1")
    assert validate.jaccard(validate.shingles("one two three four five six"),
                            validate.shingles("one two three four five six")) == 1.0
