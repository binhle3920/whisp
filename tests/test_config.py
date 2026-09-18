from pathlib import Path

from whisp.config import Settings


def test_file_credentials_share_configured_directory(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, credentials_dir=tmp_path / "secrets")

    assert settings.google_credentials_path == tmp_path / "secrets/google_credentials.json"
    assert settings.google_token_path == tmp_path / "secrets/google_token.json"
