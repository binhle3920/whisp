from whisp.core.models import EmailMessage
from whisp.core.store import Store


def test_cursor_and_deduplication(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    assert store.get("history_id") is None
    store.set("history_id", "123")
    assert store.get("history_id") == "123"

    message = EmailMessage("m1", "t1", "alice@example.com", "Hello", "Body")
    assert not store.is_processed("m1")
    store.mark_processed(message)
    store.mark_processed(message)
    assert store.is_processed("m1")
    assert store.status()["processed_messages"] == 1

