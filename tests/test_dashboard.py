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
    store: Store, readiness: dict[str, object] | None = None, *, login: bool = True
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
    client = TestClient(app)
    client.auth = (USER, PASSWORD)
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


def test_dashboard_rejects_missing_or_wrong_credentials(tmp_path) -> None:
    client = make_client(Store(tmp_path / "whisp.db"))

    anonymous = client.get("/dashboard", auth=None)
    wrong = client.get("/dashboard", auth=(USER, "wrong-password-123"))

    for response in (anonymous, wrong):
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == 'Basic realm="Whisp"'
    assert PASSWORD not in wrong.text


def test_dashboard_is_disabled_until_login_is_configured(tmp_path) -> None:
    client = make_client(Store(tmp_path / "whisp.db"), login=False)

    assert client.get("/dashboard").status_code == 503


def test_dashboard_response_is_not_cached(tmp_path) -> None:
    response = make_client(Store(tmp_path / "whisp.db")).get("/dashboard")

    assert response.headers["Cache-Control"] == "no-store"
