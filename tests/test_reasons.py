import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
import reasons  # noqa: E402


def test_reason_quotes_the_words_that_changed():
    r = reasons.reason_for("grammar", "Their was crumbs everywhere.", "There were crumbs everywhere.", random.Random(1))
    assert "Their was" in r and "There were" in r


def test_insertions_and_deletions_get_their_own_wording():
    assert reasons.main_change("I went store.", "I went to the store.") == ("insert", [], ["to", "the"])
    kind, old, _ = reasons.main_change("It is very really good.", "It is very good.")
    assert kind == "delete" and old == ["really"]


def test_long_changes_are_shortened_in_the_quote():
    src = "one two three four five six seven eight nine"
    tgt = "alpha beta gamma delta epsilon zeta eta theta iota"
    r = reasons.reason_for("clarity", src, tgt, random.Random(0))
    assert "…" in r and "nine" not in r


def test_reasons_vary_instead_of_repeating_one_sentence():
    seen = {reasons.reason_for("grammar", "He go home.", "He goes home.", random.Random(seed)) for seed in range(20)}
    assert len(seen) > 1


def test_unchanged_text_or_unknown_category_gives_no_reason():
    assert reasons.reason_for("grammar", "Same.", "Same.") is None
    assert reasons.reason_for("poetry", "a b", "a c") is None
