import base64
import hashlib
import hmac
import secrets
import time as clock
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from whisp.config import Settings
from whisp.core.pipeline import next_digest_at
from whisp.core.store import LAST_DIGEST_KEY, Store

RECENT_MESSAGES = 50
RECENT_ACTIVITY = 20
SESSION_COOKIE = "whisp_session"
SESSION_SECONDS = 7 * 24 * 3600
MAX_FORM_BYTES = 4096

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _login_configured(settings: Settings) -> bool:
    return bool(settings.dashboard_username and settings.dashboard_password is not None)


def _session_key(settings: Settings) -> bytes:
    # Derived from the configured login, so changing the password (or username)
    # invalidates every existing session without a separate secret to manage.
    assert settings.dashboard_password is not None
    assert settings.dashboard_username
    return hmac.new(
        settings.dashboard_password.get_secret_value().encode(),
        b"whisp-dashboard-session:" + settings.dashboard_username.encode(),
        hashlib.sha256,
    ).digest()


def _sign(settings: Settings, payload: str) -> str:
    return hmac.new(_session_key(settings), payload.encode(), hashlib.sha256).hexdigest()


def issue_session(settings: Settings, now: float) -> str:
    payload = f"{int(now) + SESSION_SECONDS}"
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{encoded}.{_sign(settings, payload)}"


def valid_session(settings: Settings, token: str | None, now: float) -> bool:
    if not token or not _login_configured(settings) or token.count(".") != 1:
        return False
    encoded, signature = token.split(".")
    try:
        payload = base64.urlsafe_b64decode(encoded.encode()).decode()
        expires = int(payload)
    except ValueError:
        return False
    if not secrets.compare_digest(signature, _sign(settings, payload)):
        return False
    return now < expires


def credentials_match(settings: Settings, username: str, password: str) -> bool:
    assert settings.dashboard_password is not None
    assert settings.dashboard_username
    # Compare both fields every time, in constant time, so neither the result nor the
    # timing reveals whether the username alone was right.
    user_ok = secrets.compare_digest(username.encode(), settings.dashboard_username.encode())
    password_ok = secrets.compare_digest(
        password.encode(), settings.dashboard_password.get_secret_value().encode()
    )
    return user_ok and password_ok


def _no_store(response: Response) -> Response:
    # Pages here contain email subjects and senders; keep them out of shared caches.
    response.headers["Cache-Control"] = "no-store"
    return response


def _login_page(request: Request, *, error: str | None = None, username: str = "") -> Response:
    status = 401 if error else 200
    response = templates.TemplateResponse(
        request, "login.html", {"error": error, "username": username}, status_code=status
    )
    return _no_store(response)


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value)
    # SQLite's datetime('now') columns are UTC without an offset.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _local(value: object, zone: ZoneInfo) -> str:
    parsed = _parse(value)
    return parsed.astimezone(zone).strftime("%Y-%m-%d %H:%M") if parsed else "—"


def _ago(value: object, now: datetime) -> str:
    parsed = _parse(value)
    if parsed is None:
        return "never"
    seconds = int((now - parsed).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def build_context(
    store: Store, settings: Settings, readiness: dict[str, object]
) -> dict[str, object]:
    zone = settings.zone
    now = datetime.now(UTC)
    status = store.status()
    last_digest_date = store.get(LAST_DIGEST_KEY)
    next_digest = next_digest_at(now.astimezone(zone), settings.digest_time, last_digest_date)

    messages = []
    for row in store.recent_messages(RECENT_MESSAGES):
        if not row["in_digest"]:
            outcome = ("notified", "Notified")
        elif row["digest_sent_at"]:
            outcome = ("digest-sent", "In digest")
        else:
            outcome = ("digest-pending", "Held for digest")
        messages.append({**row, "at": _local(row["processed_at"], zone), "outcome": outcome})

    activity = [
        {**run, "at": _local(run["started_at"], zone)}
        for run in store.recent_activity(RECENT_ACTIVITY)
    ]
    commit = settings.git_commit
    return {
        "now": now.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": settings.timezone,
        "commit": commit,
        "commit_short": commit[:7] if commit and commit != "unknown" else commit or "local",
        "readiness": readiness,
        "readiness_checked_at": _local(readiness.get("checked_at"), zone),
        "status": status,
        "last_success_ago": _ago(status["last_successful_poll_at"], now),
        "last_success_at": _local(status["last_successful_poll_at"], zone),
        "last_failure_at": _local((status["last_failure"] or {}).get("finished_at"), zone),
        "digest_enabled": settings.digest_enabled,
        "next_digest": next_digest.strftime("%Y-%m-%d %H:%M"),
        "last_digest_date": last_digest_date or "never",
        "messages": messages,
        "activity": activity,
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> Response:
    state = request.app.state
    if not _login_configured(state.settings):
        # Fail closed: an unconfigured dashboard is unavailable rather than open.
        raise HTTPException(503, "Dashboard login is not configured")
    if not valid_session(state.settings, request.cookies.get(SESSION_COOKIE), clock.time()):
        return RedirectResponse("/dashboard/login", status_code=303)
    context = build_context(state.store, state.settings, state.readiness.snapshot())
    return _no_store(templates.TemplateResponse(request, "dashboard.html", context))


@router.get("/dashboard/login", response_class=HTMLResponse)
async def login_form(request: Request) -> Response:
    if not _login_configured(request.app.state.settings):
        raise HTTPException(503, "Dashboard login is not configured")
    return _login_page(request)


@router.post("/dashboard/login")
async def login(request: Request) -> Response:
    settings = request.app.state.settings
    if not _login_configured(settings):
        raise HTTPException(503, "Dashboard login is not configured")
    body = await request.body()
    if len(body) > MAX_FORM_BYTES:
        raise HTTPException(413)
    form = parse_qs(body.decode("utf-8", errors="replace"))
    username = form.get("username", [""])[0]
    password = form.get("password", [""])[0]
    if not credentials_match(settings, username, password):
        return _login_page(request, error="Wrong username or password.", username=username)
    # Always land on the dashboard; never redirect to a caller-supplied URL.
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(settings, clock.time()),
        max_age=SESSION_SECONDS,
        path="/dashboard",
        httponly=True,
        # Secure cookies are still sent to http://127.0.0.1 through the SSH tunnel;
        # browsers treat localhost as a secure context.
        secure=True,
        samesite="lax",
    )
    return response


@router.post("/dashboard/logout")
async def logout() -> Response:
    response = RedirectResponse("/dashboard/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/dashboard", secure=True, httponly=True)
    return response
