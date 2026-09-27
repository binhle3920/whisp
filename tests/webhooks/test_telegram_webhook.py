import asyncio
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from whisp.chat.models import ChatRequest
from whisp.config import Settings
from whisp.core.store import Store
from whisp.webhooks.telegram import ERROR_TEXT, RESET_TEXT, router

SECRET = "s" * 40
CHAT = "42"


class RecordingTelegram:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str | None]] = []

    async def send_text(self, chat_id: str, text: str, *, reply_to: str | None = None) -> None:
        self.sent.append((chat_id, text, reply_to))

    async def send_typing(self, chat_id: str) -> None:
        return None


class StubAgent:
    def __init__(self, error: Exception | None = None) -> None:
        self.requests: list[ChatRequest] = []
        self.error = error

    async def reply(self, request: ChatRequest) -> str:
        self.requests.append(request)
        if self.error:
            raise self.error
        return "Câu trả lời"


def make_app(tmp_path, agent: StubAgent | None = None) -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    app.include_router(router)
    app.state.settings = Settings(
        _env_file=None,
        telegram_chat_id=CHAT,
        public_base_url="https://whisp.example.com",
        telegram_webhook_secret=SECRET,
    )
    app.state.store = Store(tmp_path / "whisp.db")
    app.state.chat_agent = agent or StubAgent()
    app.state.telegram = RecordingTelegram()
    app.state.chat_tasks = set()
    app.state.chat_lock = asyncio.Lock()
    return app, TestClient(app)


def update(update_id: int, text: str, chat_id: str = CHAT, **extra: object) -> dict:
    message = {"message_id": 7, "chat": {"id": int(chat_id)}, "text": text, **extra}
    return {"update_id": update_id, "message": message}


def post(client: TestClient, body: dict, secret: str | None = SECRET):
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret else {}
    return client.post("/telegram/webhook", json=body, headers=headers)


def wait_for_tasks(app: FastAPI, client: TestClient) -> None:
    async def drain() -> None:
        while app.state.chat_tasks:
            await asyncio.gather(*list(app.state.chat_tasks))

    client.portal.call(drain)  # type: ignore[union-attr]


def test_wrong_or_missing_secret_is_rejected(tmp_path) -> None:
    app, client = make_app(tmp_path)

    assert post(client, update(1, "hi"), secret=None).status_code == 401
    assert post(client, update(2, "hi"), secret="x" * 40).status_code == 401
    assert app.state.chat_agent.requests == []


def test_message_is_answered_as_a_reply(tmp_path) -> None:
    app, client = make_app(tmp_path)
    with client:
        assert post(client, update(1, "tìm hoá đơn")).status_code == 200
        wait_for_tasks(app, client)

    assert app.state.chat_agent.requests == [ChatRequest(chat_id=CHAT, text="tìm hoá đơn")]
    assert app.state.telegram.sent == [(CHAT, "Câu trả lời", "7")]


def test_other_chats_are_ignored(tmp_path) -> None:
    app, client = make_app(tmp_path)
    with client:
        post(client, update(1, "give me the inbox", chat_id="999"))
        wait_for_tasks(app, client)

    assert app.state.chat_agent.requests == []
    assert app.state.telegram.sent == []


def test_retried_updates_are_handled_once(tmp_path) -> None:
    app, client = make_app(tmp_path)
    with client:
        post(client, update(5, "hello"))
        post(client, update(5, "hello"))
        wait_for_tasks(app, client)

    assert len(app.state.chat_agent.requests) == 1


def test_reset_clears_history(tmp_path) -> None:
    app, client = make_app(tmp_path)
    app.state.store.append_chat(CHAT, "user", "old")
    with client:
        post(client, update(1, "/reset"))
        wait_for_tasks(app, client)

    assert app.state.store.chat_history(CHAT, 10) == []
    assert app.state.telegram.sent == [(CHAT, RESET_TEXT, None)]


def test_reply_to_notification_passes_linked_email(tmp_path) -> None:
    app, client = make_app(tmp_path)
    app.state.store.link_notification("555", "gmail-abc")
    with client:
        post(client, update(1, "tóm tắt file", reply_to_message={"message_id": 555}))
        wait_for_tasks(app, client)

    assert app.state.chat_agent.requests[0].reply_to_email_id == "gmail-abc"


def test_agent_failure_sends_apology_without_logging_message(tmp_path, caplog) -> None:
    app, client = make_app(tmp_path, StubAgent(RuntimeError("secret email body")))
    with caplog.at_level(logging.ERROR), client:
        post(client, update(1, "my private question"))
        wait_for_tasks(app, client)

    assert app.state.telegram.sent == [(CHAT, ERROR_TEXT, "7")]
    assert "my private question" not in caplog.text
    assert "secret email body" not in caplog.text
    assert "Unexpected RuntimeError" in caplog.text


def test_webhook_is_hidden_when_not_configured(tmp_path) -> None:
    app, client = make_app(tmp_path)
    app.state.chat_agent = None

    assert post(client, update(1, "hi")).status_code == 404
