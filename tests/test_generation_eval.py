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
    {"title": "t", "paragraphs": ["Real text.", "]}<tool_call|>{"]},
    {"title": "t", "paragraphs": ["]}<tool_call|>{"]},
]


def test_d1_drops_markup_debris_but_keeps_real_paragraphs():
    title, body = editor.draft_from_reply({"title": "T", "paragraphs": [
        "It ends here.", "]}<tool_call|>{", "In 2020, 3 of 4 said yes.", "¿Por qué no?", "---", "<b>"]})
    assert body == "It ends here.\n\nIn 2020, 3 of 4 said yes.\n\n¿Por qué no?"
    assert editor.draft_from_reply({"title": "T", "paragraphs": ["]}<tool_call|>{"]}) == (None, None)


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


def test_amendment_1_excludes_only_persuade_text_dependent_prompts():
    import prompts
    assert prompts.excluded_from_comparison({"family": "persuade", "genre": "argumentative (Text dependent)"})
    assert prompts.excluded_from_comparison({"family": "persuade", "genre": "argumentative (Independent)"}) is None
    assert prompts.excluded_from_comparison({"family": "quill-genre", "genre": "text dependent"}) is None


def _prompt(**kw):
    return {"id": "q-x-1", "family": "quill-genre", "genre": "argument", "goal": "persuasive essay",
            "audience": "my teacher", "length": "medium", "instructions": "Argue for X. Points: a, b.", **kw}


def test_variants_change_only_their_one_line():
    base, _ = generate.build_request(_prompt(), seed=1)
    e2, _ = generate.build_request(_prompt(), seed=1, variants=("e2",))
    assert e2 == base.replace("Length: about 500 words", "Length: about 500 words (aim for 450-550)")
    e4_other, _ = generate.build_request(_prompt(), seed=1, variants=("e4",))
    assert e4_other == base   # e4 touches literary prompts only
    lit = _prompt(goal="literary analysis essay", genre="literary")
    lit_base, _ = generate.build_request(lit, seed=1)
    lit_e4, _ = generate.build_request(lit, seed=1, variants=("e4",))
    assert lit_e4.replace("\n\n" + generate.X.E4_SENTENCE, "", 1) == lit_base
    e1_other, _ = generate.build_request(_prompt(), seed=1, variants=("e1",))
    assert e1_other == base   # e1 touches only prompts with written details
    pid = next(iter(generate.X.E1_DETAILS))
    e1, _ = generate.build_request(_prompt(id=pid), seed=1, variants=("e1",))
    assert "Details I can add:" in e1 and generate.X.E1_DETAILS[pid][0] in e1


def test_unknown_variant_is_refused():
    with pytest.raises(SystemExit):
        generate.X.parse("e9")


def test_app_details_format_matches_experiment_e1():
    import app as quill
    pid = next(iter(generate.X.E1_DETAILS))
    entry = {"id": pid, "instructions": "Base."}
    assert quill.with_details("Base.", generate.X.E1_DETAILS[pid]) == generate.X.adjust_prompt_entry(entry, ("e1",))["instructions"]


def test_e5_adds_the_writers_examples_only_where_written():
    base, _ = generate.build_request(_prompt(), seed=1)
    assert generate.build_request(_prompt(), seed=1, variants=("e5",))[0] == base
    pid = next(iter(generate.X.E5_EXAMPLES))
    e5, _ = generate.build_request(_prompt(id=pid), seed=1, variants=("e5",))
    assert "Examples and evidence I can use:" in e5 and generate.X.E5_EXAMPLES[pid][0] in e5
