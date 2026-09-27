from datetime import datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from whisp.config import Settings
from whisp.core.models import EmailMessage
from whisp.core.store import Store
from whisp.dashboard import _next_digest, router

VN = ZoneInfo("Asia/Ho_Chi_Minh")


USER = "admin"
PASSWORD = "correct-horse-battery"


def make_client(
    store: Store,
    readiness: dict[str, object] | None = None,
    *,
    login: bool = True,
    logged_in: bool = True,
) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.store = store
    app.state.settings = Settings(
        _env_file=None,
        git_commit="79672d6abcdef",
        dashboard_username=USER if login else None,
        dashboard_password=PASSWORD if login else None,
    )
    app.state.readiness = SimpleNamespace(snapshot=lambda: readiness) if readiness else None
    # The session cookie is Secure, so the client must talk https to get it back.
    client = TestClient(app, base_url="https://testserver")
    if login and logged_in:
        response = client.post(
            "/dashboard/login",
            data={"username": USER, "password": PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 303
    return client


def test_dashboard_renders_status_messages_and_outcomes(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    store.mark_processed(EmailMessage("m1", "t1", "Alice <alice@example.com>", "Contract", "Body"))
    store.queue_digest(EmailMessage("m2", "t2", "deals@shop.com", "Big sale", "Body"), summary=None)
    run_id = store.start_run()
    store.finish_run(run_id, discovered=2, notified=1, skipped=0, failed=0)
    readiness = {
        "ready": False,
        "checked_at": "2026-09-25T16:49:21+00:00",
        "checks": {
            "store": {"ok": True, "error": None},
            "input": {"ok": False, "error": "Gmail authentication failed"},
            "output": {"ok": True, "error": None},
        },
    }

    response = make_client(store, readiness).get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "79672d6" in html
    assert "Gmail authentication failed" in html
    assert "Contract" in html and "Notified" in html
    assert "Big sale" in html and "Held for digest" in html


def test_dashboard_escapes_untrusted_email_fields(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    store.mark_processed(
        EmailMessage("m1", "t1", "evil@example.com", "<script>alert(1)</script>", "Body")
    )

    html = make_client(store).get("/dashboard").text

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_dashboard_is_unavailable_without_store(tmp_path) -> None:
    client = make_client(Store(tmp_path / "whisp.db"))
    client.app.state.store = None  # type: ignore[attr-defined]

    assert client.get("/dashboard").status_code == 503


def test_next_digest_rolls_to_tomorrow_once_sent() -> None:
    evening = datetime(2026, 9, 25, 23, 30, tzinfo=VN)

    assert _next_digest(evening, time(23), None).day == 25
    assert _next_digest(evening, time(23), "2026-09-25").day == 26
    assert _next_digest(datetime(2026, 9, 25, 9, tzinfo=VN), time(23), "2026-09-24").day == 25


def test_dashboard_redirects_to_login_without_a_session(tmp_path) -> None:
    client = make_client(Store(tmp_path / "whisp.db"), logged_in=False)

    response = client.get("/dashboard", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/login"


def test_login_form_is_password_manager_friendly(tmp_path) -> None:
    client = make_client(Store(tmp_path / "whisp.db"), logged_in=False)

    html = client.get("/dashboard/login").text

    assert 'name="username"' in html and 'autocomplete="username"' in html
    assert 'type="password"' in html and 'autocomplete="current-password"' in html


def test_login_sets_a_hardened_session_cookie(tmp_path) -> None:
    client = make_client(Store(tmp_path / "whisp.db"), logged_in=False)

    response = client.post(
        "/dashboard/login",
        data={"username": USER, "password": PASSWORD},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/dashboard"
    cookie = response.headers["set-cookie"].lower()
    for flag in ("httponly", "secure", "samesite=lax", "path=/dashboard"):
        assert flag in cookie
    assert PASSWORD.lower() not in cookie
    assert client.get("/dashboard").status_code == 200


def test_wrong_credentials_show_the_form_again(tmp_path) -> None:
    client = make_client(Store(tmp_path / "whisp.db"), logged_in=False)

    response = client.post(
        "/dashboard/login",
        data={"username": USER, "password": "wrong-password-123"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert "Wrong username or password." in response.text
    assert "set-cookie" not in response.headers
    assert "wrong-password-123" not in response.text


def test_forged_or_expired_sessions_are_rejected(tmp_path) -> None:
    from whisp.dashboard import SESSION_COOKIE, issue_session, valid_session

    settings = Settings(_env_file=None, dashboard_username=USER, dashboard_password=PASSWORD)
    token = issue_session(settings, now=1_000)
    other = Settings(_env_file=None, dashboard_username=USER, dashboard_password="another-password")

    assert valid_session(settings, token, now=1_001)
    assert not valid_session(settings, token, now=1_000 + 8 * 24 * 3600)
    assert not valid_session(other, token, now=1_001)
    assert not valid_session(settings, token.split(".")[0] + ".deadbeef", now=1_001)
    assert not valid_session(settings, "garbage", now=1_001)

    client = make_client(Store(tmp_path / "whisp.db"), logged_in=False)
    client.cookies.set(SESSION_COOKIE, "forged.value", domain="testserver", path="/dashboard")
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_logout_clears_the_session(tmp_path) -> None:
    client = make_client(Store(tmp_path / "whisp.db"))

    client.post("/dashboard/logout", follow_redirects=False)

    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_dashboard_is_disabled_until_login_is_configured(tmp_path) -> None:
    client = make_client(Store(tmp_path / "whisp.db"), login=False)

    assert client.get("/dashboard").status_code == 503


def test_dashboard_response_is_not_cached(tmp_path) -> None:
    response = make_client(Store(tmp_path / "whisp.db")).get("/dashboard")

    assert response.headers["Cache-Control"] == "no-store"
