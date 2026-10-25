"""Polish: paragraph rewrites with a content check, recorded as AI-written when accepted."""
import editor
import polish
from conftest import stream_events

ESSAY = ("In 1935 there was alot of dust storms on the Plains and farmers like my great-grandpa lost "
         "there crops. He said \"the sky went black at noon\".\n\nIt was hard for everyone.")


def fake_polisher(monkeypatch, revise):
    calls = []

    async def chat(client, system, prompt, schema, model=None, options=None):
        calls.append((system, prompt, model))
        paragraph = prompt.split('"""\n', 1)[1].rsplit('\n"""', 1)[0]
        return {"revised": revise(paragraph)}

    monkeypatch.setattr(editor, "chat", chat)
    return calls


def test_check_flags_missing_numbers_names_quotes_and_big_changes():
    original = ESSAY.split("\n\n")[0]
    ok = polish.check(original, original.replace("alot of dust storms", "a lot of dust storms").replace("there crops", "their crops"))
    assert ok["warnings"] == [] and ok["kept_words"] > 0.9
    bad = polish.check(original, "Long ago, storms hurt farmers on the land.")
    text = " ".join(bad["warnings"])
    assert "1935" in text and "Plains" in text and "quotation" in text and "key words" in text


def test_check_warns_when_the_polish_stops_short():
    original = "He ran home after school. Then he slept until noon and dreamed of dogs."
    assert any("end of your paragraph" in w for w in polish.check(original, "He ran home after school.")["warnings"])
    assert any("end of your paragraph" in w for w in polish.check(original, "He ran home after school. Then he slept until,")["warnings"])
    fixed = polish.check("If you have impressoin you are famous in same way", "If you have an impression, you are famous in the same way.")
    assert not any("end of your paragraph" in w for w in fixed["warnings"])


def test_long_paragraphs_are_polished_in_sentence_pieces(client, user, monkeypatch):
    _, h = user
    sentence = "The students worked on there project for many weeks and learned alot about plants. "
    long = (sentence * 40).strip()          # 560 words
    assert polish.pieces("Short one. Two.") == ["Short one. Two."]
    parts = polish.pieces(long)
    assert len(parts) == 3 and " ".join(parts) == long and all(len(p.split()) <= 250 for p in parts)
    calls = fake_polisher(monkeypatch, lambda p: p.replace("there project", "their project"))
    events = stream_events(client.post("/api/polish", headers=h, json={"body": long}))
    p = next(e for e in events if e["type"] == "paragraph")
    assert len(calls) == 3 and "there project" not in p["revised"] and len(p["revised"].split()) == 560


def test_polish_streams_each_paragraph_with_its_check(client, user, monkeypatch):
    _, h = user
    calls = fake_polisher(monkeypatch, lambda p: p.replace("alot of", "a lot of").replace("there crops", "their crops"))
    events = stream_events(client.post("/api/polish", headers=h, json={"body": ESSAY, "goal": "history essay"}))
    assert [e["type"] for e in events] == ["start", "paragraph", "paragraph", "done"]
    first = events[1]
    assert first["index"] == 0 and "a lot of dust storms" in first["revised"] and first["checks"]["warnings"] == []
    assert calls[0][0] == editor.POLISH_SYSTEM and calls[0][2] == editor.OVERVIEW_MODEL
    assert "Essay goal: history essay" in calls[0][1]


def test_polish_one_paragraph_only(client, user, monkeypatch):
    _, h = user
    fake_polisher(monkeypatch, lambda p: p)
    events = stream_events(client.post("/api/polish", headers=h, json={"body": ESSAY, "paragraph": 1}))
    paragraphs = [e for e in events if e["type"] == "paragraph"]
    assert [p["index"] for p in paragraphs] == [1]


def test_an_empty_polish_leaves_the_paragraph_unchanged_with_a_warning(client, user, monkeypatch):
    _, h = user
    fake_polisher(monkeypatch, lambda p: "")
    events = stream_events(client.post("/api/polish", headers=h, json={"body": ESSAY, "paragraph": 0}))
    p = next(e for e in events if e["type"] == "paragraph")
    assert p["revised"] == p["original"] and "unchanged" in p["checks"]["warnings"][0]


def test_accepted_polish_is_recorded_as_ai_text(client, user):
    _, h = user
    d = client.post("/api/drafts", headers=h, json={"title": "Dust", "body": ESSAY}).json()["id"]
    polished = "In 1935, there were a lot of dust storms on the Plains."
    r = client.post(f"/api/drafts/{d}/ai-text", headers=h, json={"paragraphs": [polished]})
    assert r.status_code == 200 and r.json()["ai_text"] == polished
    client.post(f"/api/drafts/{d}/versions", headers=h, json={"body": polished + "\n\nIt was hard for everyone.", "note": "Polished"})
    replay = client.get(f"/api/drafts/{d}/replay", headers=h).json()
    assert replay[-1]["ai_paragraphs"] == [True, False]
    assert replay[0]["ai_paragraphs"] == [False, False]  # saved before the polish: still the writer's
    assert client.post(f"/api/drafts/{d}/ai-text", headers=h, json={"paragraphs": []}).status_code == 422
