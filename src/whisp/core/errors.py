from collections.abc import Iterator
from contextlib import contextmanager


class SafeWhispError(RuntimeError):
    """An application error whose message is safe to log and persist."""


class ProviderError(SafeWhispError):
    def __init__(self, provider: str, operation: str, *, status_code: int | None = None) -> None:
        message = f"{provider} {operation} failed"
        if status_code is not None:
            message += f" with HTTP {status_code}"
        super().__init__(message)
        self.status_code = status_code


def safe_error_message(error: BaseException) -> str:
    if isinstance(error, SafeWhispError):
        return str(error)
    return f"Unexpected {type(error).__name__}"


@contextmanager
def sanitized_errors() -> Iterator[None]:
    """Re-raise any failure as a SafeWhispError, dropping the unsafe original traceback."""
    try:
        yield
    except SafeWhispError:
        raise
    except Exception as exc:
        raise SafeWhispError(safe_error_message(exc)) from None
