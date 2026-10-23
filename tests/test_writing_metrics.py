import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
import writing_metrics as wm  # noqa: E402

TEMPLATE = ("In today's world, phones are everywhere. Furthermore, students use them constantly. "
            "Moreover, teachers find this crucial to address.\n\n"
            "Ultimately, it is vital that we navigate this landscape together.")
HUMAN = ("My phone died on the bus Tuesday. I didn't notice for an hour.\n\n"
         "That hour was the first time all week I finished the reading before class, which is a little embarrassing to admit.")


def test_template_prose_scores_as_formulaic():
    m = wm.essay_metrics(TEMPLATE)
    assert m["formulaic_openers_per_100_sentences"] >= 75
    assert m["formula_conclusion"] is True
    assert m["stock_words_per_1000"] > 50
    h = wm.essay_metrics(HUMAN)
    assert h["formulaic_openers_per_100_sentences"] == 0 and not h["formula_conclusion"]
    assert h["contractions_per_100_words"] > 0


def test_sentence_and_paragraph_spread():
    even = "One two three four. One two three four. One two three four."
    assert wm.essay_metrics(even)["sentence_cv"] == 0
    assert wm.essay_metrics(HUMAN)["paragraph_cv"] > 0.2


def test_lexical_diversity_does_not_reward_length():
    text = " ".join(["the cat sat on the mat and looked at the dog"] * 10)
    assert wm.mtld(wm.words(text)) < 20
    varied = wm.words("Rain hammered the tin roof while Marcus counted cracked tiles, sketching repairs he couldn't afford yet")
    assert wm.mtld(varied) > 15


def test_sameness_finds_shared_phrasing():
    stock = [f"It is important to note that {t} matters a great deal to everyone." for t in ("sleep", "music", "food", "sport")]
    varied = ["Sleep is the first thing I cut.", "My brother hums in the car.", "We ate cold noodles.", "Coach yelled twice."]
    assert wm.corpus_sameness(stock)["shared_ngram_share"] > 0.5
    assert wm.corpus_sameness(varied)["shared_ngram_share"] == 0


def test_invented_specifics_are_flagged_only_when_not_given():
    source = "Why I want to study nursing. My mom works as a CNA."
    found = wm.invented_specifics('In 2019, Dr. Patel told me "nursing is about listening more than talking."', source)
    assert "2019" in found and any(f.startswith('"nursing') for f in found) and "Patel" in found
    assert wm.invented_specifics("My mom works as a CNA, and I admire her.", source) == []


def test_voice_shift_catches_formalizing():
    before = "I'm not gonna lie, it's hard. We didn't care."
    after = "I am not going to lie; it is difficult. We did not care."
    shift = wm.voice_shift(before, after)
    assert shift["contractions_per_100_words"] < -20
    assert wm.voice_shift(before, before)["word_length"] == 0
