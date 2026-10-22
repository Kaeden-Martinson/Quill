import rules


def test_mechanical_mistakes_are_fixed():
    assert rules.fix_text("Its weird how fast it went.")[0] == "It's weird how fast it went."
    assert rules.fix_text("If your still waiting, go.")[0] == "If you're still waiting, go."
    assert rules.fix_text("I learned alot.")[0] == "I learned a lot."
    assert rules.fix_text("I could of stayed.")[0] == "I could have stayed."
    assert rules.fix_text("Their was a hawk.")[0] == "There was a hawk."


def test_correct_uses_are_left_alone():
    for ok in ["The dog wagged its tail.", "The town has its own rules.", "Its roots go deep.",
               "Your getting caught was bad luck.", "Your right hand is bigger.", "It's fine.",
               "Their house is big.", "A lot of people came.", "I could have stayed."]:
        assert rules.fix_text(ok) == (ok, []), ok


def test_rule_fix_merges_into_the_models_suggestion_for_that_sentence():
    para = "Its weird how me and my brother started. We stayed."
    model = [{"original": "Its weird how me and my brother started.", "revised": "Its weird how my brother and I started.",
              "reason": "You're the subject.", "category": "grammar"}]
    out = rules.apply(para, model)
    assert len(out) == 1
    assert out[0]["revised"] == "It's weird how my brother and I started."
    assert "it is" in out[0]["reason"]


def test_rule_adds_its_own_suggestion_where_the_model_said_nothing():
    out = rules.apply("We stayed. Its just a game.", [])
    assert out == [{"original": "Its just a game.", "revised": "It's just a game.",
                    "reason": rules.RULES[0][2], "category": "grammar"}]
