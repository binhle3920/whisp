from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WHISP_", env_file=".env", extra="ignore", case_sensitive=False
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
    log_level: str = "INFO"

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
