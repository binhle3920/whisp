import httpx

from whisp.config import Settings
from whisp.core.pipeline import Pipeline
from whisp.core.store import Store
from whisp.inputs.gmail import GmailInput
from whisp.inputs.gmail.auth import GmailAuth
from whisp.outputs.telegram import TelegramOutput
from whisp.processors.openrouter import OpenRouterProcessor
from whisp.processors.profile import AssistantProfile


def build_pipeline(settings: Settings, client: httpx.AsyncClient) -> Pipeline:
    settings.require_runtime_secrets()
    assert settings.openrouter_api_key is not None
    assert settings.telegram_bot_token is not None
    assert settings.telegram_chat_id is not None
    return Pipeline(
        store=Store(settings.db_path),
        input_source=GmailInput(GmailAuth(settings.google_token_path), client),
        processor=OpenRouterProcessor(
            api_key=settings.openrouter_api_key.get_secret_value(),
            model=settings.openrouter_model,
            client=client,
            site_url=settings.openrouter_site_url,
            app_title=settings.openrouter_app_title,
            profile=AssistantProfile.from_file(settings.assistant_profile_path),
        ),
        output=TelegramOutput(
            settings.telegram_bot_token.get_secret_value(), settings.telegram_chat_id, client
        ),
        max_messages=settings.max_messages_per_run,
        email_max_chars=settings.email_max_chars,
        digest_enabled=settings.digest_enabled,
    )
