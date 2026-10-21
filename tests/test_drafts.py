def make_draft(client, headers, title="Essay", body="First draft."):
    r = client.post("/api/drafts", headers=headers, json={"title": title, "body": body})
    assert r.status_code == 200
    return r.json()["id"]


def test_versions_are_saved_only_when_text_changes(client, user):
    _, h = user
    d = make_draft(client, h)
    assert client.post(f"/api/drafts/{d}/versions", headers=h, json={"body": "First draft."}).json() == {"saved": False}
    assert client.post(f"/api/drafts/{d}/versions", headers=h, json={"body": "Second draft."}).json() == {"saved": True}
    draft = client.get(f"/api/drafts/{d}", headers=h).json()
    assert draft["body"] == "Second draft." and len(draft["versions"]) == 2


def test_rename(client, user):
    _, h = user
    d = make_draft(client, h)
    client.patch(f"/api/drafts/{d}", headers=h, json={"title": "New title"})
    assert client.get(f"/api/drafts/{d}", headers=h).json()["title"] == "New title"


def test_people_cannot_see_or_change_each_others_essays(client, user):
    _, owner = user
    d = make_draft(client, owner, body="private")
    other = client.post("/api/register", json={"name": "nosy", "password": "nosy password", "invite": "test-invite"})
    nosy = {"Authorization": f"Bearer {other.json()['token']}"}
    assert client.get(f"/api/drafts/{d}", headers=nosy).status_code == 404
    assert client.post(f"/api/drafts/{d}/versions", headers=nosy, json={"body": "x"}).status_code == 404
    assert client.get(f"/api/drafts/{d}/history.txt", headers=nosy).status_code == 404
    assert client.delete(f"/api/drafts/{d}", headers=nosy).status_code == 404
    assert client.get(f"/api/drafts/{d}", headers=owner).status_code == 200


def test_delete_removes_the_essay_and_its_history(client, user):
    _, h = user
    d = make_draft(client, h)
    client.post(f"/api/drafts/{d}/versions", headers=h, json={"body": "More"})
    version_ids = [v["id"] for v in client.get(f"/api/drafts/{d}", headers=h).json()["versions"]]

    assert client.delete(f"/api/drafts/{d}", headers=h).status_code == 200
    assert client.get(f"/api/drafts/{d}", headers=h).status_code == 404
    assert client.get(f"/api/drafts/{d}/history.txt", headers=h).status_code == 404
    for vid in version_ids:
        assert client.get(f"/api/versions/{vid}", headers=h).status_code == 404
    assert all(x["id"] != d for x in client.get("/api/drafts", headers=h).json())


def test_history_export_lists_every_version_in_order(client, user):
    name, h = user
    d = make_draft(client, h, title="Toaster", body="one")
    client.post(f"/api/drafts/{d}/versions", headers=h, json={"body": "two", "note": "Manual save"})
    text = client.get(f"/api/drafts/{d}/history.txt", headers=h).text
    assert f"Author: {name}" in text and "Versions: 2" in text
    assert text.index("Version 1") < text.index("Version 2") < text.index("Manual save")


def test_word_export_then_import_round_trips(client, user):
    _, h = user
    body = "First paragraph.\n\nSecond paragraph."
    d = make_draft(client, h, title="Round trip", body=body)
    docx = client.get(f"/api/drafts/{d}/export.docx", headers=h).content
    new_id = client.post("/api/import/docx", headers=h, content=docx).json()["id"]
    imported = client.get(f"/api/drafts/{new_id}", headers=h).json()
    assert imported["title"] == "Round trip" and imported["body"] == body


def test_importing_a_non_word_file_is_refused(client, user):
    _, h = user
    assert client.post("/api/import/docx", headers=h, content=b"not a zip").status_code == 400
