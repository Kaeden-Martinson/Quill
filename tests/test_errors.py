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


def test_every_rule_fires_somewhere_and_is_undone_exactly():
    texts = [PARA,
             "You're gonna laugh, but I could have sworn it. A lot of people say that. The guy whose dog it was shrugged. I'd rather lose my keys.",
             "My dad's truck broke down, and then we waited too long. The town where I grew up has its own rules.",
             "I made fewer mistakes this time."]
    fired = set()
    for text in texts:
        for rule in errors.applicable(text):
            wrong, s = errors.plant(text, rule, random.Random(0))
            assert wrong.replace(s["original"], s["revised"], 1) == text, rule
            fired.add(rule)
    assert fired == {r[0] for r in errors.RULES}


def test_me_and_covers_the_forms_round_3_missed():
    text = "By junior year my coach and I started running practice rounds. The fire department and I are friends now."
    rng = random.Random(0)
    seen = set()
    for _ in range(10):
        wrong, s = errors.plant(text, "me-and", rng)
        seen.add(s["original"])
        assert wrong.replace(s["original"], s["revised"], 1) == text
    assert "By junior year me and my coach started running practice rounds." in seen
    assert "Me and the fire department are friends now." in seen


def test_me_and_leaves_am_and_was_alone():
    # "Me and my brother am" isn't a real-world mistake, so don't teach it.
    assert errors.plant("My brother and I was late.", "me-and", random.Random(0)) is None


def test_fewer_less():
    wrong, s = errors.plant("I made fewer mistakes this time.", "fewer-less", random.Random(0))
    assert s["original"] == "I made less mistakes this time."
    assert "fewer mistakes" in s["reason"]


def test_rules_that_do_not_apply_return_none():
    assert errors.plant("Short and sweet.", "whose-who's", random.Random(0)) is None
