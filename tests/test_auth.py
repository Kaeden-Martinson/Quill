from conftest import INVITE, PASSWORD


def test_register_requires_the_invite_code(client):
    r = client.post("/api/register", json={"name": "outsider", "password": PASSWORD, "invite": "guess"})
    assert r.status_code == 401


def test_names_are_unique_ignoring_case(client, user):
    name, _ = user
    r = client.post("/api/register", json={"name": name.upper(), "password": PASSWORD, "invite": INVITE})
    assert r.status_code == 409


def test_short_passwords_are_rejected(client):
    r = client.post("/api/register", json={"name": "shorty", "password": "short", "invite": INVITE})
    assert r.status_code == 422


def test_login_and_wrong_password(client, user):
    name, _ = user
    assert client.post("/api/login", json={"name": name, "password": "nope-nope"}).status_code == 401
    assert client.post("/api/login", json={"name": name, "password": PASSWORD}).status_code == 200


def test_lockout_after_five_wrong_passwords_even_for_the_right_one(client, user):
    name, _ = user
    for _ in range(5):
        assert client.post("/api/login", json={"name": name, "password": "wrong-pass"}).status_code == 401
    assert client.post("/api/login", json={"name": name, "password": PASSWORD}).status_code == 429


def test_endpoints_need_a_session(client):
    assert client.get("/api/drafts").status_code == 401
    assert client.get("/api/drafts", headers={"Authorization": "Bearer made-up"}).status_code == 401


def test_logout_ends_the_session(client, user):
    _, headers = user
    assert client.post("/api/logout", headers=headers).status_code == 200
    assert client.get("/api/drafts", headers=headers).status_code == 401


def test_me_returns_the_signed_in_name(client, user):
    name, headers = user
    assert client.get("/api/me", headers=headers).json() == {"name": name}


# ---------- password change ----------

def test_password_change_needs_the_current_password(client, user):
    _, headers = user
    r = client.post("/api/password", headers=headers, json={"current": "not-it-at-all", "new": "brand new pass"})
    assert r.status_code == 401


def test_password_change_rejects_reusing_the_same_password(client, user):
    _, headers = user
    r = client.post("/api/password", headers=headers, json={"current": PASSWORD, "new": PASSWORD})
    assert r.status_code == 400


def test_password_change_keeps_this_session_and_ends_the_others(client, user):
    name, headers = user
    other = client.post("/api/login", json={"name": name, "password": PASSWORD}).json()["token"]
    other_headers = {"Authorization": f"Bearer {other}"}

    r = client.post("/api/password", headers=headers, json={"current": PASSWORD, "new": "brand new pass"})
    assert r.status_code == 200 and r.json()["signed_out"] == 1

    assert client.get("/api/drafts", headers=headers).status_code == 200
    assert client.get("/api/drafts", headers=other_headers).status_code == 401
    assert client.post("/api/login", json={"name": name, "password": PASSWORD}).status_code == 401
    assert client.post("/api/login", json={"name": name, "password": "brand new pass"}).status_code == 200


def test_password_guessing_through_change_endpoint_is_rate_limited(client, user):
    _, headers = user
    for _ in range(5):
        client.post("/api/password", headers=headers, json={"current": "guess-guess", "new": "brand new pass"})
    r = client.post("/api/password", headers=headers, json={"current": PASSWORD, "new": "brand new pass"})
    assert r.status_code == 429
