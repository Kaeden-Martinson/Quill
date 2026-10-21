import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
import eval as ev  # noqa: E402

TEXT = "I'm not gonna pretend I loved it. Eleven miles. Their was a hawk."


def test_app_filter_drops_misquotes_and_no_ops():
    sugs = [
        {"original": "Their was", "revised": "There was"},
        {"original": "Eleven miles.", "revised": "Eleven miles."},       # changes nothing
        {"original": "words not in the text", "revised": "x"},           # misquote
    ]
    assert [s["original"] for s in ev.shown(TEXT, sugs)] == ["Their was"]


def test_rewriting_a_style_choice_breaks_it():
    assert ev.breaks([{"original": "Eleven miles.", "revised": "It was eleven miles."}], "Eleven miles.")
    assert ev.breaks([{"original": "gonna", "revised": "going to"}], "I'm not gonna pretend")


def test_fixing_something_nearby_does_not_break_it():
    assert not ev.breaks([{"original": "Their was", "revised": "There was"}], "Eleven miles.")
    # Editing a longer span that still contains the phrase unchanged is fine.
    assert not ev.breaks([{"original": "Eleven miles. Their was", "revised": "Eleven miles. There was"}], "Eleven miles.")


def test_contractions_are_counted():
    assert len(ev.CONTRACTION.findall("I'm sure it's fine, didn't you say?")) == 3
