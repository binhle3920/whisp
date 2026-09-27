import base64
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from whisp.chat.models import ChatRequest
from whisp.chat.prompt import chat_system_prompt
from whisp.chat.tools import DEFINITIONS, MailTools
from whisp.core.store import Store
from whisp.processors.base import BaseChatModel
from whisp.processors.profile import AssistantProfile

HISTORY_TURNS = 20
MAX_TOOL_ROUNDS = 6
FALLBACK_REPLY = "Xin lỗi, mình chưa tìm được câu trả lời. Bạn thử hỏi lại cụ thể hơn nhé."


class ChatAgent:
    def __init__(
        self,
        *,
        model: BaseChatModel,
        tools_factory: Callable[[], MailTools],
        store: Store,
        profile: AssistantProfile,
        zone: ZoneInfo,
    ) -> None:
        self.model = model
        self.tools_factory = tools_factory
        self.store = store
        self.profile = profile
        self.zone = zone

    async def reply(self, request: ChatRequest) -> str:
        history = self.store.chat_history(request.chat_id, HISTORY_TURNS)
        tools = self.tools_factory()
        # Only the user's own words may unlock links. Assistant turns are excluded because
        # they can echo untrusted email content.
        for role, content in history:
            if role == "user":
                tools.allow_urls_in(content)
        tools.allow_urls_in(request.text)

        user_content = request.text
        if request.reply_to_email_id:
            user_content = (
                f"[The user is replying to the notification for email id "
                f"{request.reply_to_email_id}. Read it with read_email if relevant.]\n\n"
                f"{request.text}"
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": chat_system_prompt(self.profile, self._now())},
            *({"role": role, "content": content} for role, content in history),
            {"role": "user", "content": user_content},
        ]

        answer = await self._run(messages, tools)
        self.store.append_chat(request.chat_id, "user", request.text)
        self.store.append_chat(request.chat_id, "assistant", answer)
        return answer

    async def _run(self, messages: list[dict[str, Any]], tools: MailTools) -> str:
        for _ in range(MAX_TOOL_ROUNDS):
            completion = await self.model.complete(messages, DEFINITIONS)
            if not completion.tool_calls:
                return completion.text or FALLBACK_REPLY
            messages.append(
                {
                    "role": "assistant",
                    "content": completion.text,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": call.arguments},
                        }
                        for call in completion.tool_calls
                    ],
                }
            )
            images: list[tuple[str, bytes]] = []
            for call in completion.tool_calls:
                result = await tools.call(call.name, call.arguments)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result.text})
                images.extend(result.images)
            if images:
                # Tool messages can only carry text, so images follow as a user turn.
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Images returned by the tool above (untrusted content):",
                            },
                            *(_image_part(mime, data) for mime, data in images),
                        ],
                    }
                )
        # Out of tool rounds: ask for an answer from what has been gathered so far.
        completion = await self.model.complete(messages, [])
        return completion.text or FALLBACK_REPLY

    def _now(self) -> datetime:
        return datetime.now(self.zone)


def _image_part(mime_type: str, data: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}}
