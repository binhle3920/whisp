from whisp.core.models import EmailMessage, PollResult
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


def test_status_reports_run_timing_success_and_sanitized_failure(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    successful_run = store.start_run()
    store.finish_run(successful_run, PollResult(discovered=1, notified=1))
    failed_run = store.start_run()
    store.finish_run(
        failed_run,
        PollResult(discovered=1, failed=1),
        error="Telegram send failed with HTTP 503",
    )

    result = store.status()

    assert result["last_successful_poll_at"] is not None
    assert result["last_run"]["duration_ms"] >= 0
    assert result["last_failure"] == {
        "finished_at": result["last_run"]["finished_at"],
        "failed": 1,
        "error": "Telegram send failed with HTTP 503",
    }


def test_digest_queue_round_trip(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    message = EmailMessage("m1", "t1", "Shop <deals@shop.com>", "Sale", "Body")

    store.queue_digest(message, summary="50% off")
    store.queue_digest(message, summary="50% off")

    assert store.is_processed("m1")
    assert [(item.message_id, item.summary) for item in store.pending_digest()] == [
        ("m1", "50% off")
    ]
    assert store.status()["digest_pending"] == 1
    store.mark_digest_sent(["m1"])
    assert store.pending_digest() == []
    assert store.status()["digest_pending"] == 0


def test_chat_history_keeps_latest_turns_in_order(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    for index in range(5):
        store.append_chat("42", "user", f"q{index}")
    store.append_chat("other", "user", "not mine")

    assert store.chat_history("42", 2) == [("user", "q3"), ("user", "q4")]
    store.clear_chat("42")
    assert store.chat_history("42", 10) == []
    assert store.chat_history("other", 10) == [("user", "not mine")]


def test_claim_update_is_true_only_once(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")

    assert store.claim_update("100") is True
    assert store.claim_update("100") is False
