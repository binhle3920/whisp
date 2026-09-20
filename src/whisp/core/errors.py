class SafeWhispError(RuntimeError):
    """An application error whose message is safe to log and persist."""


class ProviderError(SafeWhispError):
    def __init__(self, provider: str, operation: str, *, status_code: int | None = None) -> None:
        message = f"{provider} {operation} failed"
        if status_code is not None:
            message += f" with HTTP {status_code}"
        super().__init__(message)


def safe_error_message(error: BaseException) -> str:
    if isinstance(error, SafeWhispError):
        return str(error)
    return f"Unexpected {type(error).__name__}"
