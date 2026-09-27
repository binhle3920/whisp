import json
from zoneinfo import ZoneInfo

from chat_fakes import FakeFetcher, FakeMailbox, ScriptedModel, invoice_email

from whisp.chat.agent import HISTORY_TURNS, MAX_TOOL_ROUNDS, ChatAgent
from whisp.chat.models import ChatCompletion, ChatRequest, ToolCall
from whisp.chat.tools import MailTools
from whisp.core.store import Store
from whisp.processors.profile import AssistantProfile


def make_agent(store: Store, model: ScriptedModel, mailbox: FakeMailbox) -> ChatAgent:
    return ChatAgent(
        model=model,
        tools_factory=lambda: MailTools(
            mailbox=mailbox, fetcher=FakeFetcher(), email_max_chars=12_000
        ),
        store=store,
        profile=AssistantProfile(),
        zone=ZoneInfo("Asia/Ho_Chi_Minh"),
    )


def call(name: str, **arguments: str) -> ChatCompletion:
    return ChatCompletion(tool_calls=(ToolCall("c1", name, json.dumps(arguments)),))


async def test_agent_runs_tools_then_answers_and_stores_only_final_text(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    model = ScriptedModel(
        call("search_emails", query="invoice"),
        call("read_email", message_id="m1"),
        ChatCompletion(text="Hoá đơn tháng 9 từ Acme, hạn thanh toán thứ Sáu."),
    )
    mailbox = FakeMailbox({"m1": invoice_email()})

    answer = await make_agent(store, model, mailbox).reply(
        ChatRequest(chat_id="42", text="Hoá đơn Acme hạn khi nào?")
    )

    assert answer == "Hoá đơn tháng 9 từ Acme, hạn thanh toán thứ Sáu."
    assert mailbox.queries == ["invoice"]
    last_messages = model.calls[-1][0]
    assert any(m["role"] == "tool" and "Invoice September" in m["content"] for m in last_messages)
    assert store.chat_history("42", 10) == [
        ("user", "Hoá đơn Acme hạn khi nào?"),
        ("assistant", answer),
    ]


async def test_agent_stops_calling_tools_after_the_round_limit(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    looping = [call("search_emails", query="x") for _ in range(MAX_TOOL_ROUNDS)]
    model = ScriptedModel(*looping, ChatCompletion(text="Best effort answer"))

    answer = await make_agent(store, model, FakeMailbox()).reply(
        ChatRequest(chat_id="42", text="find it")
    )

    assert answer == "Best effort answer"
    assert len(model.calls) == MAX_TOOL_ROUNDS + 1
    assert model.calls[-1][1] == []


async def test_reply_to_notification_names_the_email(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    model = ScriptedModel(ChatCompletion(text="ok"))

    await make_agent(store, model, FakeMailbox()).reply(
        ChatRequest(chat_id="42", text="tóm tắt giúp", reply_to_email_id="m1")
    )

    user_turn = model.calls[0][0][-1]["content"]
    assert "email id m1" in user_turn
    assert store.chat_history("42", 10)[0] == ("user", "tóm tắt giúp")


async def test_history_is_limited(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    for index in range(HISTORY_TURNS + 10):
        store.append_chat("42", "user", f"old {index}")
    model = ScriptedModel(ChatCompletion(text="ok"))

    await make_agent(store, model, FakeMailbox()).reply(ChatRequest(chat_id="42", text="new"))

    sent = model.calls[0][0]
    # System prompt + limited history + the new message.
    assert len(sent) == 1 + HISTORY_TURNS + 1
    assert sent[1]["content"] == f"old {10}"


async def test_image_attachments_reach_the_model_as_image_parts(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    email = invoice_email()
    from dataclasses import replace

    from whisp.core.models import Attachment

    email = replace(email, attachments=(Attachment("att-2", "receipt.png", "image/png", 4),))
    mailbox = FakeMailbox({"m1": email})
    mailbox.files["att-2"] = b"\x89PNG"
    model = ScriptedModel(
        call("read_attachment", message_id="m1", filename="receipt.png"),
        ChatCompletion(text="It is a receipt."),
    )

    await make_agent(store, model, mailbox).reply(ChatRequest(chat_id="42", text="what is it"))

    image_turn = model.calls[1][0][-1]
    assert image_turn["role"] == "user"
    assert image_turn["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
