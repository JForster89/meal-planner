"""Login protection. The critical test is that no route leaks when logged out."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASSWORD = "correct-horse-battery"


@pytest.fixture
def secured(monkeypatch):
    """A client with APP_PASSWORD set, i.e. auth switched on."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)

    monkeypatch.setenv("RECIPES_DB", path)
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    monkeypatch.setenv("SECRET_KEY", "test-key")
    for mod in ("db", "app", "store", "auth"):
        sys.modules.pop(mod, None)

    import db as db_mod
    db_mod.DB_PATH = path
    import app as app_mod
    import auth as auth_mod

    auth_mod._FAILURES.clear()
    app_mod.app.config["TESTING"] = True
    with app_mod.app.test_client() as c:
        c.application = app_mod.app
        yield c

    try:
        os.unlink(path)
    except OSError:
        pass


def sign_in(client, password=PASSWORD):
    return client.post("/login", data={"password": password})


PROTECTED = [
    "/", "/recipes", "/recipes/1", "/recipes/new", "/recipes/1/edit",
    "/import", "/shopping", "/shopping.txt",
]


@pytest.mark.parametrize("url", PROTECTED)
def test_every_page_redirects_to_login_when_signed_out(secured, url):
    resp = secured.get(url)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


@pytest.mark.parametrize("url,data", [
    ("/plan/add/1", {}),
    ("/plan/clear", {}),
    ("/recipes/1/delete", {}),
    ("/shopping/extra", {"text": "sneaky"}),
    ("/shopping/reset", {}),
])
def test_mutating_routes_blocked_when_signed_out(secured, url, data):
    """Reads being blocked is not enough - writes must be too."""
    resp = secured.post(url, data=data)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_page_itself_is_reachable(secured):
    assert secured.get("/login").status_code == 200


def test_healthcheck_stays_public(secured):
    assert secured.get("/healthz").status_code == 200


def test_correct_password_grants_access(secured):
    assert sign_in(secured).status_code == 302
    assert secured.get("/").status_code == 200


def test_wrong_password_denied(secured):
    resp = sign_in(secured, "nope")
    assert resp.status_code == 200
    assert "Wrong password" in resp.get_data(as_text=True)
    assert secured.get("/").status_code == 302


def test_logout_revokes_access(secured):
    sign_in(secured)
    assert secured.get("/").status_code == 200
    secured.post("/logout")
    assert secured.get("/").status_code == 302


def test_next_param_returns_you_where_you_were_going(secured):
    resp = secured.post("/login?next=/shopping", data={"password": PASSWORD})
    assert resp.headers["Location"].endswith("/shopping")


@pytest.mark.parametrize("evil", ["https://evil.example.com", "//evil.example.com"])
def test_next_param_cannot_redirect_off_site(secured, evil):
    resp = secured.post(f"/login?next={evil}", data={"password": PASSWORD})
    assert "evil.example.com" not in resp.headers["Location"]


def test_lockout_after_repeated_failures(secured):
    for _ in range(5):
        sign_in(secured, "wrong")
    resp = sign_in(secured, "wrong")
    assert resp.status_code == 429
    # Even the right password is refused while locked out.
    assert sign_in(secured).status_code == 429


def test_refuses_to_start_unprotected_on_fly(monkeypatch):
    """A deploy that forgets APP_PASSWORD must fail loudly, not serve openly."""
    import importlib

    monkeypatch.setenv("FLY_APP_NAME", "some-app")
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    for mod in ("db", "app", "store", "auth"):
        sys.modules.pop(mod, None)

    import auth as auth_mod
    importlib.reload(auth_mod)

    from flask import Flask
    with pytest.raises(RuntimeError, match="APP_PASSWORD is not set"):
        auth_mod.init_auth(Flask(__name__))


def test_auth_disabled_without_password(client):
    """Local dev stays frictionless when no password is configured."""
    assert client.get("/").status_code == 200
