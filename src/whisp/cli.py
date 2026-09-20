import argparse
import asyncio
import json

import httpx
import uvicorn
from google_auth_oauthlib.flow import InstalledAppFlow

from whisp.config import get_settings
from whisp.core.store import Store
from whisp.inputs.gmail.auth import SCOPES
from whisp.logging_config import configure_logging
from whisp.runtime import build_pipeline


def _authorize() -> None:
    settings = get_settings()
    if not settings.google_credentials_path.exists():
        raise SystemExit(
            f"Google OAuth credentials not found: {settings.google_credentials_path}\n"
            "Download an OAuth Desktop client JSON file and place it there first."
        )
    flow = InstalledAppFlow.from_client_secrets_file(settings.google_credentials_path, SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    settings.google_token_path.parent.mkdir(parents=True, exist_ok=True)
    settings.google_token_path.write_text(credentials.to_json())
    print(f"Gmail authorization saved to {settings.google_token_path}")


async def _poll(backfill: bool) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    async with httpx.AsyncClient(timeout=30) as client:
        pipeline = build_pipeline(settings, client)
        await pipeline.output.check()
        result = await pipeline.run_once(backfill=backfill)
    print(json.dumps(result.__dict__, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="whisp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("authorize", help="Authorize access to Gmail")
    poll = subparsers.add_parser("poll", help="Check Gmail once")
    poll.add_argument(
        "--backfill", action="store_true", help="Summarize recent inbox mail on first run"
    )
    subparsers.add_parser("status", help="Show local Whisp state")
    serve = subparsers.add_parser("serve", help="Run the API and background poller")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    if args.command == "authorize":
        _authorize()
    elif args.command == "poll":
        asyncio.run(_poll(args.backfill))
    elif args.command == "status":
        print(json.dumps(Store(get_settings().db_path).status(), indent=2))
    elif args.command == "serve":
        uvicorn.run("whisp.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
