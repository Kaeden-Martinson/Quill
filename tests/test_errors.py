import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
import errors  # noqa: E402

PARA = ("I'm not gonna lie, there was a moment I almost quit. And honestly? It's still kinda wild "
        "that I didn't. My brother and I went back the next week anyway. We were way better than before.")


def test_each_planted_error_is_undone_exactly_by_its_suggestion():
    rng = random.Random(0)
    for rule in errors.applicable(PARA):
        planted = errors.plant(PARA, rule, rng)
        assert planted, rule
        wrong_text, s = planted
        assert wrong_text != PARA
        assert s["original"] in wrong_text                        # quotes the text it will see
        assert wrong_text.replace(s["original"], s["revised"], 1) == PARA   # fix restores it exactly


def test_only_the_planted_error_changes():
    wrong_text, s = errors.plant(PARA, "than-then", random.Random(1))
    assert s["original"] == "We were way better then before."
    assert s["revised"] == "We were way better than before."
    assert "gonna" in wrong_text and "kinda" in wrong_text and "And honestly?" in wrong_text


def test_explanations_name_the_words():
    _, s = errors.plant(PARA, "there-their", random.Random(0))
    assert "“their was”" in s["reason"].lower() or "their" in s["reason"].lower()
    _, s = errors.plant(PARA, "me-and", random.Random(0))
    assert "My brother and I" in s["reason"] and "Me and" in s["reason"]


def test_rules_that_do_not_apply_return_none():
    assert errors.plant("Short and sweet.", "whose-who's", random.Random(0)) is None
