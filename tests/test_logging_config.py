import logging

from whisp.logging_config import configure_logging


def test_transport_loggers_do_not_emit_request_urls_at_info() -> None:
    configure_logging("INFO")

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
