import base64

from whisp.inputs.gmail.parser import parse_message


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_parses_nested_plain_text() -> None:
    raw = {
        "id": "m1",
        "threadId": "t1",
        "payload": {
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "Subject", "value": "Project update"},
            ],
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": encoded("Hello there")}},
                        {"mimeType": "text/html", "body": {"data": encoded("<b>Hello</b>")}},
                    ],
                }
            ],
        },
    }
    message = parse_message(raw, max_chars=1000)
    assert message.sender == "Alice <alice@example.com>"
    assert message.subject == "Project update"
    assert message.body == "Hello there"


def test_falls_back_to_html() -> None:
    raw = {
        "id": "m2",
        "snippet": "fallback",
        "payload": {
            "headers": [],
            "mimeType": "text/html",
            "body": {"data": encoded("<p>Hello &amp; welcome</p><p>Second line</p>")},
        },
    }
    message = parse_message(raw, max_chars=1000)
    assert "Hello & welcome" in message.body
    assert "Second line" in message.body

