import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
import reliability  # noqa: E402


def test_word_changes_counts_separate_places():
    assert reliability.word_changes("a b c d", "a b c d") == 0
    assert reliability.word_changes("Their was crumbs.", "There was crumbs.") == 1
    assert reliability.word_changes("one two three four", "ONE two three FOUR") == 2


def test_scoring_rewards_exact_fixes_and_penalizes_extra_edits(tmp_path, monkeypatch):
    correct = "There was a hawk. It sat on a rock."
    cases = [
        {"id": "a", "text": "Their was a hawk. It sat on a rock.", "correct": correct,
         "planted": [{"rule": "there-their", "wrong_sentence": "Their was a hawk.", "right_sentence": "There was a hawk."}]},
        {"id": "b", "text": correct, "correct": correct, "planted": []},
    ]
    cases_file = tmp_path / "cases.jsonl"
    cases_file.write_text("\n".join(json.dumps(c) for c in cases), encoding="utf-8")
    monkeypatch.setattr(reliability, "CASES", cases_file)
    monkeypatch.setattr(reliability, "HERE", tmp_path)

    answers = {
        # fixes the mistake and also rewrites a fine sentence: 1 extra change
        cases[0]["text"]: [{"original": "Their was a hawk.", "revised": "There was a hawk."},
                           {"original": "It sat on a rock.", "revised": "It perched on a rock."}],
        # leaves the clean paragraph alone
        correct: [],
    }
    monkeypatch.setattr(reliability, "ask", lambda client, model, text: answers[text])
    got = reliability.score("fake")
    assert got["fixed"] == 1.0
    assert got["perfect"] == 0.5        # case a had an extra change, case b is exact
    assert got["untouched"] == 1.0
    assert got["extra"] == 0.5          # 1 extra change across 2 paragraphs
