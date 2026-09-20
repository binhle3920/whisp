import asyncio
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailAuth:
    def __init__(self, token_path: Path) -> None:
        self.token_path = token_path
        self._credentials: Credentials | None = None
        self._lock = asyncio.Lock()

    async def access_token(self) -> str:
        async with self._lock:
            if self._credentials is None:
                if not self.token_path.exists():
                    raise RuntimeError(
                        f"Gmail token not found at {self.token_path}. Run `whisp authorize`."
                    )
                self._credentials = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            if not self._credentials.valid:
                if not self._credentials.refresh_token:
                    raise RuntimeError(
                        "Gmail token has no refresh token. Run `whisp authorize` again."
                    )
                await asyncio.to_thread(self._credentials.refresh, Request())
            if not self._credentials.token:
                raise RuntimeError("Gmail authorization did not return an access token")
            return self._credentials.token
