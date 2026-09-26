import secrets
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from whisp.config import Settings
from whisp.core.store import Store

RECENT_MESSAGES = 50
RECENT_ACTIVITY = 20

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
basic_auth = HTTPBasic(auto_error=False)


def require_login(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(basic_auth)],
) -> None:
    settings = request.app.state.settings
    if not settings.dashboard_username or settings.dashboard_password is None:
        # Fail closed: an unconfigured dashboard is unavailable rather than open.
        raise HTTPException(503, "Dashboard login is not configured")
    supplied_user = credentials.username if credentials else ""
    supplied_password = credentials.password if credentials else ""
    # Compare both fields every time, in constant time, so neither the result nor the
    # timing reveals whether the username alone was right.
    user_ok = secrets.compare_digest(supplied_user.encode(), settings.dashboard_username.encode())
    password_ok = secrets.compare_digest(
        supplied_password.encode(), settings.dashboard_password.get_secret_value().encode()
    )
    if not (user_ok and password_ok):
        raise HTTPException(
            401, "Login required", headers={"WWW-Authenticate": 'Basic realm="Whisp"'}
        )


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


def _next_digest(now_local: datetime, digest_at: time, last_digest_date: str | None) -> datetime:
    today = now_local.date()
    due_today = now_local.time() < digest_at or last_digest_date != today.isoformat()
    day = today if due_today else today + timedelta(days=1)
    return datetime.combine(day, digest_at, tzinfo=now_local.tzinfo)


def build_context(
    store: Store, settings: Settings, readiness: dict[str, object] | None
) -> dict[str, object]:
    zone = settings.zone
    now = datetime.now(UTC)
    status = store.status()
    last_digest_date = store.get("last_digest_date")
    next_digest = _next_digest(now.astimezone(zone), settings.digest_at, last_digest_date)

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
        "readiness_checked_at": _local((readiness or {}).get("checked_at"), zone),
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


@router.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def dashboard(request: Request) -> HTMLResponse:
    state = request.app.state
    if state.store is None:
        raise HTTPException(503, "Whisp is not configured")
    readiness = state.readiness.snapshot() if state.readiness is not None else None
    context = build_context(state.store, state.settings, readiness)
    response = templates.TemplateResponse(request, "dashboard.html", context)
    # The page contains email subjects and senders; keep it out of shared caches.
    response.headers["Cache-Control"] = "no-store"
    return response
