import json

import httpx
import respx

from whisp.core.models import EmailMessage
from whisp.processors.openrouter import OpenRouterProcessor
from whisp.processors.profile import AssistantProfile


@respx.mock
async def test_openrouter_processor_sends_expected_request() -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "Review it by Friday."}}
                ]
            },
        )
    )
    message = EmailMessage(
        id="m1",
        thread_id="t1",
        sender="alice@example.com",
        subject="Project review",
        body="Please review the project by Friday.",
    )
    async with httpx.AsyncClient() as client:
        processor = OpenRouterProcessor(
            api_key="test-key",
            model="openai/gpt-5.4-nano",
            client=client,
            site_url="https://example.com/whisp",
            profile=AssistantProfile(
                personality="Direct and pragmatic.",
                default_language="Vietnamese",
                priorities=["Project deadlines"],
            ),
        )
        summary = await processor.process(message)

    assert summary == "Review it by Friday."
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.headers["HTTP-Referer"] == "https://example.com/whisp"
    payload = json.loads(request.content)
    assert payload["model"] == "openai/gpt-5.4-nano"
    system_prompt = payload["messages"][0]["content"]
    assert "Direct and pragmatic." in system_prompt
    assert "Vietnamese" in system_prompt
    assert "- Project deadlines" in system_prompt


def test_assistant_profile_loads_from_toml(tmp_path) -> None:
    profile_path = tmp_path / "assistant.toml"
    profile_path.write_text(
        """
[assistant]
personality = "Friendly and focused."
default_language = "French"
response_style = "One short paragraph."
user_context = "I run a small business."
priorities = ["Invoices", "Customer complaints"]
custom_instructions = "Mention currency amounts exactly."
""".strip()
    )

    profile = AssistantProfile.from_file(profile_path)

    assert profile.default_language == "French"
    assert profile.priorities == ["Invoices", "Customer complaints"]
    assert "I run a small business." in profile.system_prompt()


def test_missing_assistant_profile_uses_defaults(tmp_path) -> None:
    profile = AssistantProfile.from_file(tmp_path / "missing.toml")

    assert profile.default_language == "English"
