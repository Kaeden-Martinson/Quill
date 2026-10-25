"""Localized suggestions: split into one edit per change, labelled, and filtered by the writer's mode."""
import localize as L
from conftest import stream_events
import editor


def apply_all(paragraph, pieces):
    for p in pieces:
        assert paragraph.count(p["original"]) == 1, p["original"]
        paragraph = paragraph.replace(p["original"], p["revised"], 1)
    return paragraph


SENTENCE = "Its very easy to get distracted from driving and that one of the biggest distraction while driving."
FIXED = "It's very easy to get distracted from driving, and that one of the biggest distractions while driving."
PARAGRAPH = SENTENCE + " Other drivers agree with me."


def grammar(original, revised, reason="Fixes a grammar or spelling error without changing your wording."):
    return {"original": original, "revised": revised, "reason": reason, "category": "grammar"}


def test_a_bundled_edit_becomes_one_piece_per_change_and_reproduces_the_original_edit():
    pieces = L.localize(PARAGRAPH, grammar(SENTENCE, FIXED))
    assert [p["kind"] for p in pieces] == ["typo", "typo", "typo"]
    assert [p["original"] for p in pieces] == ["Its", "driving and", "distraction"]
    assert apply_all(PARAGRAPH, pieces) == PARAGRAPH.replace(SENTENCE, FIXED)
    assert not any("without changing your wording" in p["reason"] for p in pieces)


def test_quotes_grow_until_they_are_unique_in_the_paragraph():
    paragraph = "I think i like it. Its fine, i said."
    pieces = L.localize(paragraph, grammar("I think i like it.", "I think I like it."))
    assert len(pieces) == 1 and paragraph.count(pieces[0]["original"]) == 1
    two = L.localize(paragraph, grammar("Its fine, i said.", "It's fine, I said."))
    assert apply_all(paragraph, two) == "I think i like it. It's fine, I said."
    assert all(paragraph.count(p["original"]) == 1 for p in two)


def test_kinds():
    k = lambda o, n: L.hunk_kind(L.TOKEN.findall(o), L.TOKEN.findall(n))  # noqa: E731
    assert k("dont", "don't") == "typo" and k("teh", "the") == "typo" and k("i", "I") == "typo" and k(",", ";") == "typo"
    assert k("go", "goes") == "grammar"         # agreement, not spelling
    assert k("distraction", "distractions") == "typo"   # a near-identical word counts as spelling
    assert k("go", "has gone") == "grammar"     # hunk_kind sees only the changed tokens
    assert k("to be a younger guy is good", "it is good to be a younger guy") == "rewrite"


def test_rewording_is_labelled_a_rewrite_with_an_honest_reason():
    s = grammar("I said like i said before.", "I said, as I said before, that it is so.")
    pieces = L.localize("I said like i said before. More text.", s)
    assert any(p["kind"] == "rewrite" for p in pieces)
    assert all("without changing your wording" not in p["reason"] for p in pieces if p["kind"] == "rewrite")


def test_style_suggestions_stay_whole_and_are_rewrites():
    s = {"original": "February 16th, 2011", "revised": "2011-02-16", "reason": "Easier to read.", "category": "clarity"}
    assert [p["kind"] for p in L.localize("On February 16th, 2011 it snowed.", s)] == ["rewrite"]


def test_modes_filter_kinds():
    s = [grammar(SENTENCE, FIXED.replace("that one", "that is one")),
         {"original": "Other drivers agree with me.", "revised": "Most drivers agree.", "reason": "r", "category": "concision"}]
    kinds = lambda mode: sorted({p["kind"] for p in L.localize_all(PARAGRAPH, s, mode)})  # noqa: E731
    assert kinds("typos") == ["typo"]
    assert kinds("grammar") == ["grammar", "typo"]
    assert kinds("all") == ["grammar", "rewrite", "typo"]


def test_every_piece_together_equals_the_model_edit_on_many_cases():
    cases = [
        ("Luke and Don go help people and sign up for program.", "Luke and Don go to help people and sign up for the program."),
        ("If we fall down we need to stand up again , dropping some tears won't help", "If we fall down, we need to stand up again, dropping some tears won't help."),
        ("Personally i think Choosing a career is bad, because like i said it is a prove.", "Personally, I think choosing a career is bad, because, as I said, it is a proof."),
        ("there is alot of reason's to go.", "There are a lot of reasons to go."),
    ]
    for original, revised in cases:
        paragraph = original + " The end."
        assert apply_all(paragraph, L.localize(paragraph, grammar(original, revised))) == paragraph.replace(original, revised)


def fake_bundled_model(monkeypatch):
    async def chat(client, system, prompt, schema, model=None, options=None):
        return {"suggestions": [grammar(SENTENCE, FIXED.replace("that one", "that is one the")),
                                {"original": "Other drivers agree with me.", "revised": "Most drivers agree.",
                                 "reason": "Tighter.", "category": "concision"}]}
    monkeypatch.setattr(editor, "chat", chat)


def test_review_endpoint_localizes_and_honours_the_mode(client, user, monkeypatch):
    _, h = user
    fake_bundled_model(monkeypatch)
    essay = "In today's fast-paced world, " + PARAGRAPH
    by_mode = {}
    for mode in ("all", "grammar", "typos"):
        events = stream_events(client.post("/api/review", headers=h, json={"body": essay, "mode": mode}))
        by_mode[mode] = (events[0]["suggestions"], [s for e in events if e["type"] == "paragraph" for s in e["suggestions"]])
    instant_all, all_s = by_mode["all"]
    assert instant_all and {s["kind"] for s in all_s} == {"typo", "grammar", "rewrite"}
    assert by_mode["grammar"][0] == [] and {s["kind"] for s in by_mode["grammar"][1]} == {"typo", "grammar"}
    assert by_mode["typos"][0] == [] and {s["kind"] for s in by_mode["typos"][1]} == {"typo"}
    assert client.post("/api/review", headers=h, json={"body": essay, "mode": "everything"}).status_code == 422


def test_review_without_a_mode_behaves_as_all(client, user, monkeypatch):
    _, h = user
    fake_bundled_model(monkeypatch)
    events = stream_events(client.post("/api/review", headers=h, json={"body": PARAGRAPH}))
    kinds = {s["kind"] for e in events if e["type"] == "paragraph" for s in e["suggestions"]}
    assert "rewrite" in kinds


def test_a_style_labelled_typo_fix_is_a_typo_with_a_factual_reason():
    s = {"original": "My freind changed her mind.", "revised": "My friend changed her mind.",
         "reason": "is about 17.3 words, with a spread of 6.1", "category": "word choice"}
    [p] = L.localize("My freind changed her mind. Twice.", s)
    assert p["kind"] == "typo" and p["category"] == "grammar"
    assert "freind" in p["reason"] and "17.3" not in p["reason"]


def test_typo_fixes_always_say_exactly_what_changed():
    s = grammar("My freind left.", "My friend left.", reason="“friend” is about 17 letters long")
    [p] = L.localize("My freind left. Then", s)
    assert p["reason"] == "Fixes a typo or punctuation: “freind” → “friend”."


def apply_pieces_in_order(paragraph, pieces):
    for p in pieces:
        assert p["original"] in paragraph, p["original"]
        paragraph = paragraph.replace(p["original"], p["revised"], 1)
    return paragraph


def test_traps_found_replaying_real_student_essays():
    cases = [
        # a moved comma: a bare "," would match the comma the other change inserts
        ("In the Pacific and atlantic ocean he took care of animals, while going to Europe. Fun.",
         [grammar("In the Pacific and atlantic ocean he took care of animals, while going to Europe.",
                  "In the Pacific and Atlantic Ocean, he took care of animals while going to Europe.")]),
        # two suggestions: the first creates a "their" the second's piece must not match
        ("He was helping with there community and when I went their I learned a lot.",
         [grammar("helping with there community", "helping with their community"),
          grammar("when I went their I learned", "when I went there, I learned")]),
        # whitespace changes at a quote's edge
        ("They will develop self- discipline and their brain  is not going to sleep.",
         [grammar("They will develop self- discipline and their brain  is not going to sleep.",
                  "They will develop self-discipline and their brain is not going to sleep.")]),
    ]
    for paragraph, suggestions in cases:
        expected = L.apply_all(paragraph, suggestions)
        assert apply_pieces_in_order(paragraph, L.localize_all(paragraph, suggestions)) == expected
