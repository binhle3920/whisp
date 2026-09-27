import asyncio
import contextlib
import logging
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from whisp.chat.models import ChatRequest
from whisp.core.errors import safe_error_message

logger = logging.getLogger(__name__)
router = APIRouter()

HELP_TEXT = (
    "Chào bạn! Mình là trợ lý hộp thư của bạn.\n\n"
    "Bạn có thể hỏi mình tìm email, đọc nội dung, tóm tắt file đính kèm (PDF, Word, Excel, "
    "ảnh) hoặc mở link trong email. Trả lời (reply) một thông báo để hỏi về chính email đó.\n\n"
    "/reset để bắt đầu cuộc trò chuyện mới."
)
RESET_TEXT = "Đã xoá lịch sử trò chuyện. Mình bắt đầu lại nhé."
ERROR_TEXT = "Xin lỗi, mình gặp lỗi khi xử lý yêu cầu này. Bạn thử lại sau ít phút nhé."
NON_TEXT_TEXT = "Hiện mình chỉ đọc được tin nhắn văn bản."
TYPING_INTERVAL_SECONDS = 4


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> JSONResponse:
    state = request.app.state
    settings = state.settings
    if getattr(state, "chat_agent", None) is None or not settings.webhook_configured:
        raise HTTPException(404)
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    expected = settings.telegram_webhook_secret.get_secret_value()
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401)

    try:
        update: dict[str, Any] = await request.json()
    except ValueError:
        return JSONResponse({"ok": True})
    message = update.get("message")
    if not isinstance(message, dict):
        return JSONResponse({"ok": True})
    chat_id = str((message.get("chat") or {}).get("id", ""))
    # The bot is personal: anyone else who finds it gets no answer and no mailbox access.
    if chat_id != settings.telegram_chat_id:
        return JSONResponse({"ok": True})
    # Telegram retries updates it thinks failed; handle each one only once.
    if not state.store.claim_update(str(update.get("update_id"))):
        return JSONResponse({"ok": True})

    # Answer Telegram immediately; the agent can take longer than its webhook timeout.
    task = asyncio.create_task(_handle(state, chat_id, message))
    state.chat_tasks.add(task)
    task.add_done_callback(state.chat_tasks.discard)
    return JSONResponse({"ok": True})


async def _handle(state: Any, chat_id: str, message: dict[str, Any]) -> None:
    telegram = state.telegram
    message_id = str(message.get("message_id", "")) or None
    text = message.get("text")
    try:
        async with state.chat_lock:
            if not isinstance(text, str) or not text.strip():
                await telegram.send_text(chat_id, NON_TEXT_TEXT, reply_to=message_id)
                return
            command = text.strip().split()[0].split("@")[0].lower()
            if command in ("/start", "/help"):
                await telegram.send_text(chat_id, HELP_TEXT)
                return
            if command == "/reset":
                state.store.clear_chat(chat_id)
                await telegram.send_text(chat_id, RESET_TEXT)
                return

            reply_to = message.get("reply_to_message") or {}
            linked = (
                state.store.email_for_notification(str(reply_to["message_id"]))
                if "message_id" in reply_to
                else None
            )
            request = ChatRequest(chat_id=chat_id, text=text.strip(), reply_to_email_id=linked)
            typing = asyncio.create_task(_keep_typing(telegram, chat_id))
            try:
                answer = await state.chat_agent.reply(request)
            finally:
                typing.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await typing
            await telegram.send_text(chat_id, answer, reply_to=message_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Log only the sanitized reason: the user's message and email content stay out
        # of the logs.
        logger.error("Chat request failed: %s", safe_error_message(exc))
        with contextlib.suppress(Exception):
            await telegram.send_text(chat_id, ERROR_TEXT, reply_to=message_id)


async def _keep_typing(telegram: Any, chat_id: str) -> None:
    # Telegram clears the typing indicator after about five seconds.
    while True:
        with contextlib.suppress(Exception):
            await telegram.send_typing(chat_id)
        await asyncio.sleep(TYPING_INTERVAL_SECONDS)
