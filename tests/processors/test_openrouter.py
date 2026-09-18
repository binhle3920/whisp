import httpx
import respx

from whisp.core.models import EmailMessage
from whisp.processors.openrouter import OpenRouterProcessor


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
        )
        summary = await processor.process(message)

    assert summary == "Review it by Friday."
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.headers["HTTP-Referer"] == "https://example.com/whisp"
    assert b'"model":"openai/gpt-5.4-nano"' in request.content
