from pathlib import Path

import pytest
from pydantic import ValidationError

from whisp.config import Settings


def test_file_credentials_share_configured_directory(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, credentials_dir=tmp_path / "secrets")

    assert settings.google_credentials_path == tmp_path / "secrets/google_credentials.json"
    assert settings.google_token_path == tmp_path / "secrets/google_token.json"


def test_assistant_profile_has_a_local_default_path() -> None:
    settings = Settings(_env_file=None)

    assert settings.assistant_profile_path == Path("config/assistant.toml")


def test_readiness_checks_default_to_a_five_minute_cache() -> None:
    settings = Settings(_env_file=None)

    assert settings.readiness_check_interval_seconds == 300


def test_digest_defaults_to_11pm_vietnam_time() -> None:
    settings = Settings(_env_file=None)

    assert settings.digest_enabled is True
    assert settings.digest_at.hour == 23
    assert settings.zone.key == "Asia/Ho_Chi_Minh"


@pytest.mark.parametrize(
    "overrides", [{"digest_time": "25:00"}, {"digest_time": "late"}, {"timezone": "Mars/Base"}]
)
def test_invalid_digest_schedule_is_rejected(overrides: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)
