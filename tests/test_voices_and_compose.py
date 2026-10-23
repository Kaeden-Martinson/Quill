import authorship
import editor
import voices
import wordfiles
from conftest import stream_events
from test_drafts import make_draft


def test_profile_defaults_to_a_voice_measured_from_the_draft(client, user):
    _, h = user
    profile = client.get("/api/profile", headers=h).json()
    assert profile["voice_mode"] == "auto" and profile["samples"] == []
    assert profile["custom"] == voices.CUSTOM_DEFAULTS


def test_choosing_a_preset_changes_the_voice_the_editor_gets(client, user, fake_model):
    _, h = user
    r = client.put("/api/profile", headers=h, json={"voice_mode": "preset", "preset_id": "academic"})
    assert r.status_code == 200 and "Mostly avoids first person" in r.json()["active"]
    stream_events(client.post("/api/review", headers=h, json={"body": "I'm gonna say it. Students uses laptops."}))
    assert "Mostly avoids first person" in fake_model[-1]


def test_custom_voice_keeps_only_known_settings(client, user):
    _, h = user
    r = client.put("/api/profile", headers=h, json={"voice_mode": "custom",
                                                    "custom": {"contractions": "no", "humor": "lots", "evil": "yes"}})
    custom = r.json()["custom"]
    assert "evil" not in custom and custom["contractions"] == "no"
    assert "Rarely uses contractions" in r.json()["active"] and "Funny" in r.json()["active"]


def test_saving_one_part_of_the_profile_keeps_the_rest(client, user):
    _, h = user
    client.put("/api/profile", headers=h, json={"samples": ["I'm writing this the way I talk."]})
    client.put("/api/profile", headers=h, json={"voice_mode": "samples"})
    profile = client.get("/api/profile", headers=h).json()
    assert profile["samples"] == ["I'm writing this the way I talk."] and profile["voice_mode"] == "samples"


def test_unknown_voice_choices_are_rejected(client, user):
    _, h = user
    assert client.put("/api/profile", headers=h, json={"voice_mode": "robot"}).status_code == 400
    assert client.put("/api/profile", headers=h, json={"preset_id": "nope"}).status_code == 400


def test_sample_files_become_text(client, user):
    _, h = user
    r = client.post("/api/voice/sample-file", headers=h, content="My essay about bikes.".encode())
    assert r.json() == {"text": "My essay about bikes."}
    r = client.post("/api/voice/sample-file", headers=h, content=wordfiles.write_docx("Title", "From Word."))
    assert r.status_code == 200 and "From Word." in r.json()["text"]
    assert client.post("/api/voice/sample-file", headers=h, content=b"\xff\xfe\x00bad").status_code == 400


def test_never_flag_hides_matching_suggestions(client, user, fake_model):
    _, h = user
    essay = "In today's fast-paced world, students uses laptops."
    events = stream_events(client.post("/api/review", headers=h, json={"body": essay}))
    assert events[0]["suggestions"] and events[2]["suggestions"]

    client.post("/api/ignored", headers=h, json={"phrase": "In today's  fast-paced world"})
    assert client.get("/api/ignored", headers=h).json() == ["In today's fast-paced world"]
    events = stream_events(client.post("/api/review", headers=h, json={"body": essay}))
    assert events[0]["suggestions"] == [] and events[2]["suggestions"] == []

    client.delete("/api/ignored", headers=h, params={"phrase": "in today's fast-paced world"})
    assert client.get("/api/ignored", headers=h).json() == []


def test_goals_are_saved_per_essay_and_sent_to_the_editor(client, user, fake_model):
    _, h = user
    d = make_draft(client, h)
    client.patch(f"/api/drafts/{d}", headers=h, json={"goal": "scholarship essay", "audience": "a committee"})
    draft = client.get(f"/api/drafts/{d}", headers=h).json()
    assert (draft["goal"], draft["audience"], draft["title"]) == ("scholarship essay", "a committee", "Essay")
    stream_events(client.post("/api/review", headers=h, json={"body": "One paragraph.", "goal": "scholarship essay",
                                                              "audience": "a committee", "tone": "confident"}))
    assert "Essay goal: scholarship essay, for a committee, tone: confident" in fake_model[-1]


def fake_drafter(monkeypatch, paragraphs):
    prompts = []

    async def chat(client, system, prompt, schema, model=None, options=None):
        prompts.append((system, prompt, model))
        return {"title": "Why I bike", "paragraphs": paragraphs}

    monkeypatch.setattr(editor, "chat", chat)
    return prompts


def test_compose_saves_an_ai_marked_draft(client, user, monkeypatch):
    _, h = user
    client.put("/api/profile", headers=h, json={"voice_mode": "preset", "preset_id": "punchy"})
    prompts = fake_drafter(monkeypatch, ["Bikes are fast.", "They're cheap too."])
    events = stream_events(client.post("/api/compose", headers=h, json={"instructions": "Why I bike to school every day"}))
    assert [e["type"] for e in events] == ["start", "draft", "done"]
    system, prompt, model = prompts[0]
    assert system == editor.DRAFT_SYSTEM and model == editor.OVERVIEW_MODEL
    assert "Uses rhetorical questions" in prompt and voices.PRESETS["punchy"]["sample"] in prompt

    d = events[1]["id"]
    draft = client.get(f"/api/drafts/{d}", headers=h).json()
    assert draft["body"] == "Bikes are fast.\n\nThey're cheap too." and draft["ai_text"] == draft["body"]
    assert draft["versions"][0]["source"] == "ai"

    client.post(f"/api/drafts/{d}/versions", headers=h,
                json={"body": "I ride my bike because the bus smells like old fries.\n\nThey're cheap too."})
    history = client.get(f"/api/drafts/{d}/history.txt", headers=h).text
    assert "WRITTEN BY QUILL AI" in history and "1 of 2 paragraphs still mostly AI-written" in history
    replay = client.get(f"/api/drafts/{d}/replay", headers=h).json()
    assert [v["source"] for v in replay] == ["ai", "human"]
    assert replay[1]["ai_paragraphs"] == [False, True]


def test_compose_with_no_draft_returned_is_an_error(client, user, monkeypatch):
    _, h = user
    fake_drafter(monkeypatch, [])
    events = stream_events(client.post("/api/compose", headers=h, json={"instructions": "Why I bike to school"}))
    assert events[-1]["type"] == "error"
    assert client.get("/api/drafts", headers=h).json() == []


def test_human_essays_are_labelled_as_the_authors(client, user):
    _, h = user
    d = make_draft(client, h, body="All mine.")
    assert "written by the author" in client.get(f"/api/drafts/{d}/history.txt", headers=h).text


def test_ai_share_counts_words_still_in_order():
    ai = "The bus is slow and it is always late in the morning."
    assert authorship.ai_paragraph_flags("The bus is slow and it is always late.", ai) == [True]
    assert authorship.ai_paragraph_flags("Honestly the bus drives me up a wall every single day.", ai) == [False]
    assert authorship.ai_paragraph_flags("Anything.", None) == [False]


def test_paragraph_breaks_inside_one_item_are_kept(client, user, monkeypatch):
    _, h = user
    two = "Bikes are fast." + chr(10) * 2 + "They're cheap too."
    fake_drafter(monkeypatch, [two, "Third."])
    events = stream_events(client.post("/api/compose", headers=h, json={"instructions": "Why I bike to school"}))
    assert events[1]["body"].split(chr(10) * 2) == ["Bikes are fast.", "They're cheap too.", "Third."]
