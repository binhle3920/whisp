from dataclasses import dataclass

import httpx

from whisp.chat.agent import ChatAgent
from whisp.chat.tools import MailTools
from whisp.chat.web import WebFetcher
from whisp.config import Settings
from whisp.core.pipeline import Pipeline
from whisp.core.store import Store
from whisp.inputs.gmail import GmailInput
from whisp.inputs.gmail.auth import GmailAuth
from whisp.outputs.telegram import TelegramOutput
from whisp.processors.openrouter import OpenRouterChatModel, OpenRouterProcessor
from whisp.processors.profile import AssistantProfile


@dataclass(frozen=True)
class Runtime:
    """Every wired component. Built once so providers share one auth and HTTP client."""

    store: Store
    pipeline: Pipeline
    telegram: TelegramOutput
    chat_agent: ChatAgent


def _required_secrets(settings: Settings) -> tuple[str, str, str]:
    """Return (OpenRouter key, Telegram token, Telegram chat id), reporting all missing."""
    api_key = settings.openrouter_api_key
    bot_token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if api_key is None or bot_token is None or not chat_id:
        names = {
            "WHISP_OPENROUTER_API_KEY": api_key,
            "WHISP_TELEGRAM_BOT_TOKEN": bot_token,
            "WHISP_TELEGRAM_CHAT_ID": chat_id,
        }
        missing = ", ".join(name for name, value in names.items() if not value)
        raise ValueError(f"Missing required configuration: {missing}")
    return api_key.get_secret_value(), bot_token.get_secret_value(), chat_id


def build_runtime(settings: Settings, client: httpx.AsyncClient) -> Runtime:
    api_key, bot_token, chat_id = _required_secrets(settings)
    store = Store(settings.db_path)
    profile = AssistantProfile.from_file(settings.assistant_profile_path)
    gmail = GmailInput(auth=GmailAuth(token_path=settings.google_token_path), client=client)
    telegram = TelegramOutput(token=bot_token, chat_id=chat_id, client=client)
    fetcher = WebFetcher(client=client)

    pipeline = Pipeline(
        store=store,
        input_source=gmail,
        processor=OpenRouterProcessor(
            api_key=api_key,
            model=settings.openrouter_model,
            client=client,
            profile=profile,
            site_url=settings.openrouter_site_url,
            app_title=settings.openrouter_app_title,
        ),
        output=telegram,
        max_messages=settings.max_messages_per_run,
        email_max_chars=settings.email_max_chars,
        digest_enabled=settings.digest_enabled,
    )
    chat_agent = ChatAgent(
        model=OpenRouterChatModel(
            api_key=api_key,
            model=settings.chat_model,
            client=client,
            site_url=settings.openrouter_site_url,
            app_title=settings.openrouter_app_title,
        ),
        tools_factory=lambda: MailTools(
            mailbox=gmail, fetcher=fetcher, email_max_chars=settings.email_max_chars
        ),
        store=store,
        profile=profile,
        zone=settings.zone,
    )
    return Runtime(store=store, pipeline=pipeline, telegram=telegram, chat_agent=chat_agent)
