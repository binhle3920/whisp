from datetime import time
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WHISP_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        # Validation errors would otherwise echo raw input, including secrets from .env.
        hide_input_in_errors=True,
    )

    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = "openai/gpt-5.4-nano"
    openrouter_site_url: str | None = None
    openrouter_app_title: str = "Whisp"
    assistant_profile_path: Path = Path("config/assistant.toml")
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    credentials_dir: Path = Path("credentials")
    db_path: Path = Path("data/whisp.db")

    poll_interval_seconds: int = Field(default=60, ge=15)
    max_messages_per_run: int = Field(default=25, ge=1, le=500)
    email_max_chars: int = Field(default=12_000, ge=1_000)
    poller_enabled: bool = True
    readiness_check_interval_seconds: int = Field(default=300, ge=30)
    log_level: str = "INFO"
    # Set at image build time by the deploy script; None when running from a checkout.
    git_commit: str | None = None

    # Marketing mail is held and delivered once a day at digest_time in this timezone.
    digest_enabled: bool = True
    digest_time: str = "23:00"
    timezone: str = "Asia/Ho_Chi_Minh"

    # HTTP Basic login for /dashboard. The dashboard stays disabled until both are set.
    dashboard_username: str | None = None
    dashboard_password: SecretStr | None = None

    @field_validator("dashboard_password")
    @classmethod
    def _validate_dashboard_password(cls, value: SecretStr | None) -> SecretStr | None:
        # The dashboard can be published on the internet, where short passwords are
        # brute-forceable.
        if value is not None and len(value.get_secret_value()) < 12:
            raise ValueError("dashboard_password must be at least 12 characters")
        return value

    @field_validator("digest_time")
    @classmethod
    def _validate_digest_time(cls, value: str) -> str:
        try:
            parsed = time.fromisoformat(value)
        except ValueError:
            raise ValueError("digest_time must be HH:MM") from None
        return parsed.strftime("%H:%M")

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown timezone: {value}") from None
        return value

    @property
    def digest_at(self) -> time:
        return time.fromisoformat(self.digest_time)

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def google_credentials_path(self) -> Path:
        return self.credentials_dir / "google_credentials.json"

    @property
    def google_token_path(self) -> Path:
        return self.credentials_dir / "google_token.json"

    def require_runtime_secrets(self) -> None:
        missing = []
        if self.openrouter_api_key is None:
            missing.append("WHISP_OPENROUTER_API_KEY")
        if self.telegram_bot_token is None:
            missing.append("WHISP_TELEGRAM_BOT_TOKEN")
        if not self.telegram_chat_id:
            missing.append("WHISP_TELEGRAM_CHAT_ID")
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
