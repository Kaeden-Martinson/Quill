import asyncio
import json
import math

import lab

PARA = "I ride alot in the spring."


def logprobs_for(pieces):
    """Fake Ollama logprobs: each piece with a made-up chance and two candidates."""
    return [{"token": t, "logprob": math.log(0.9), "bytes": list(t.encode()),
             "top_logprobs": [{"token": t, "logprob": math.log(0.9)}, {"token": "x", "logprob": math.log(0.1)}]}
            for t in pieces]


EDIT_PIECES = ['{"', "s", "uggestions", '":', ' [{"', "original", '":', ' "', "I", " ride", " alot", " in", " the",
               " spring", '.",', ' "', "revised", '":', ' "', "I", " ride", " a", " lot", " in", " the", " spring",
               '.",', ' "', "reason", '":', ' "', "“", "A", " lot", "”", " is", " two", " words", '.",', ' "',
               "category", '":', ' "', "grammar", '"', "}]}"]
EDIT_RAW = "".join(EDIT_PIECES)


def test_the_fake_reply_is_valid_json():
    assert json.loads(EDIT_RAW)["suggestions"][0]["revised"] == "I ride a lot in the spring."


def test_string_spans_know_their_key_and_item():
    spans = [(EDIT_RAW[a:b], key, item) for a, b, key, item in lab.string_spans(EDIT_RAW)]
    assert ("I ride a lot in the spring.", "revised", 0) in spans
    assert ("grammar", "category", 0) in spans
    draft = '{"title": "Bikes", "paragraphs": ["One.", "Two \\"quoted\\"."]}'
    spans = [(draft[a:b], key, item) for a, b, key, item in lab.string_spans(draft)]
    assert spans == [("Bikes", "title", None), ("One.", "paragraphs", 0), ('Two \\"quoted\\".', "paragraphs", 1)]


def test_fields_keep_only_the_readable_words():
    fields = lab.fields(EDIT_RAW, logprobs_for(EDIT_PIECES), lab.FIELDS["edit"])
    revised = next(f for f in fields if f["key"] == "revised")
    assert "".join(t["text"] for t in revised["tokens"]) == "I ride a lot in the spring."
    # The token '.",' straddles the end of the value: only the "." is shown, but the whole token
    # is kept for matching against its candidates.
    assert revised["tokens"][-1]["text"] == "." and revised["tokens"][-1]["tok"] == '.",'
    assert revised["tokens"][0]["p"] == 0.9 and revised["tokens"][0]["cands"][1] == ["x", 0.1]
    reason = next(f for f in fields if f["key"] == "reason")
    assert "".join(t["text"] for t in reason["tokens"]) == "“A lot” is two words."


def test_a_character_split_across_tokens_still_lines_up():
    pieces = ['{"title": "', "Caf", "é", " day", '"}']
    raw = "".join(pieces)
    lps = logprobs_for(pieces)
    # Split the two bytes of "é" across two tokens, the way a tokenizer can.
    e_bytes = "é".encode()
    lps[2]["bytes"] = [e_bytes[0]]
    lps.insert(3, {**lps[2], "token": "", "bytes": [e_bytes[1]]})
    title = lab.fields(raw, lps, lab.FIELDS["draft"])[0]
    assert "".join(t["text"] for t in title["tokens"]) == "Café day"


def test_settings_are_clamped_and_always_explicit():
    s = lab.clean_settings({"temperature": 5, "top_k": 999.7, "min_p": -1})
    assert s == {"temperature": 2.0, "top_p": 1.0, "min_p": 0.0, "top_k": 200}
    assert lab.clean_settings({"seed": 4.0, "repeat_penalty": 1.1})["seed"] == 4


def test_a_run_sends_the_settings_and_asks_for_chances(monkeypatch):
    sent = {}

    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"message": {"content": EDIT_RAW}, "logprobs": logprobs_for(EDIT_PIECES), "total_duration": 2.5e9}

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, timeout, json):
            sent.update(json)
            return Response()

    monkeypatch.setattr(lab.httpx, "AsyncClient", Client)
    settings = lab.clean_settings({"temperature": 0.8, "top_p": 0.9, "seed": 7})
    result = asyncio.run(lab.run("edit", PARA, "- casual", None, settings))
    assert sent["logprobs"] is True and sent["top_logprobs"] == lab.CANDIDATES
    assert sent["options"]["temperature"] == 0.8 and sent["options"]["seed"] == 7
    assert result["suggestions"][0]["shown"] is True and result["seconds"] == 2.5 and result["complete"]


def test_lab_endpoint(client, user, monkeypatch):
    _, h = user
    calls = []

    async def run(mode, text, voice, sample, settings):
        calls.append((mode, settings))
        return {"ok": True}

    monkeypatch.setattr(lab, "run", run)
    defaults = client.get("/api/lab", headers=h).json()
    assert defaults["edit"]["temperature"] == 0 and defaults["draft"]["temperature"] > 0
    r = client.post("/api/lab", headers=h, json={"mode": "draft", "text": "Why I bike", "settings": {"temperature": 0.9}})
    assert r.json() == {"ok": True} and calls[0][0] == "draft" and calls[0][1]["temperature"] == 0.9
    assert client.post("/api/lab", headers=h, json={"mode": "poem", "text": "x"}).status_code == 422


def test_presets_use_the_settings_a_job_really_runs_with(monkeypatch):
    class Response:
        def json(self): return {"parameters": "top_k                          64\ntop_p                          0.95\ntemperature                    1"}

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json, timeout): return Response()

    monkeypatch.setattr(lab.httpx, "AsyncClient", Client)
    # Quill's own settings win, then the Modelfile, then Ollama's defaults (min_p 0).
    got = asyncio.run(lab.effective("gemma4:e4b", {"temperature": 0.75, "top_p": 0.9, "repeat_penalty": 1.1}))
    assert got == {"temperature": 0.75, "top_p": 0.9, "top_k": 64, "min_p": 0.0, "repeat_penalty": 1.1}
