"""Test setup: a throwaway database and a fake model, configured before the app is imported."""
import itertools
import os
import sys
import tempfile
from pathlib import Path

import pytest

# config.py reads these at import time, so they must be set before anything imports the app.
os.environ["QUILL_DATA_DIR"] = tempfile.mkdtemp(prefix="quill-test-")
os.environ["QUILL_PASSCODE"] = "test-invite"
os.environ["QUILL_OLLAMA_URL"] = "http://127.0.0.1:9"  # nothing listens here; the model is faked
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

import app as quill  # noqa: E402
import editor  # noqa: E402
import security  # noqa: E402

INVITE = "test-invite"
PASSWORD = "correct horse"
_names = itertools.count(1)


@pytest.fixture(autouse=True)
def clean_limits():
    """Rate limits and review claims are in-memory; reset them so tests don't leak into each other."""
    security.by_ip.failures.clear()
    security.by_name.failures.clear()
    quill.active_reviews.started.clear()
    yield


@pytest.fixture
def client():
    return TestClient(quill.app)


@pytest.fixture
def user(client):
    """A freshly registered user: (name, auth headers)."""
    name = f"user{next(_names)}"
    r = client.post("/api/register", json={"name": name, "password": PASSWORD, "invite": INVITE})
    assert r.status_code == 200, r.text
    return name, {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def fake_model(monkeypatch):
    """Replaces the Ollama call. Paragraphs containing "uses" get a grammar fix for their first sentence."""
    calls = []

    async def chat(client, system, prompt, schema, model=None):
        calls.append(prompt)
        if system == editor.OVERVIEW_SYSTEM:
            return {"strongest_part": "s", "top_priority": "p",
                    "comments": [{"aspect": "thesis", "rating": "okay", "comment": "c"}]}
        paragraph = prompt.split('"""\n', 1)[1].rsplit('\n"""', 1)[0]
        first = paragraph.split(". ")[0].rstrip(".") + "."
        if "uses" not in first:
            return {"suggestions": []}
        return {"suggestions": [
            {"original": first, "revised": first.replace("uses", "use"), "reason": "agreement", "category": "grammar"},
            {"original": "words the model made up", "revised": "x", "reason": "r", "category": "grammar"},
        ]}

    monkeypatch.setattr(editor, "chat", chat)
    return calls


def stream_events(response):
    import json
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]
