# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync --extra dev      # install (uv, not pip; uv.lock is committed)
uv run ruff check .      # lint
uv run ruff format .     # format
uv run pytest            # test
uv run pytest tests/core/test_pipeline.py::test_name   # single test
```

Running the app: `uv run whisp authorize | poll [--backfill] | status | serve`.

## Architecture

Three provider layers around a provider-independent core. See @docs/architecture.md for the
layer contracts and the steps for adding a provider.

The rule that matters: **the core never imports Gmail, OpenRouter, or Telegram.** Providers may
import core models, not the reverse. `runtime.py` is the composition root and the only place
providers are wired; adding one should not change `core/pipeline.py`.

## Code style

- Line length 100 (not 88). Target Python 3.11 — code must run on 3.11 even though the venv and
  Docker image are 3.12.
- Ruff lint rules: `E`, `F`, `I`, `UP`, `B`. `UP` means modern syntax — `str | None`, not `Optional[str]`.
- Provider constructors and `Pipeline.__init__` take keyword-only args (`def __init__(self, *, ...)`).
- Frozen dataclasses for value objects; type hints everywhere including `-> None` and in tests.
- Comments explain *why*, not what — they exist to record non-obvious decisions.

## Secret handling

This codebase deliberately prevents secrets reaching logs. Preserve these when editing:

- Wrap provider exceptions in `ProviderError` and `raise ... from None` to drop the original
  traceback. `safe_error_message()` returns raw text only for `SafeWhispError` subclasses.
- `httpx`/`httpcore` loggers are pinned to WARNING in `logging_config.py` because httpx logs full
  URLs at INFO and the Telegram bot token is part of its URL.
- Secrets are `SecretStr` in `config.py`. Tests assert non-leakage — don't weaken them.
- The assistant system prompt treats email as untrusted content (prompt-injection defense).

## Testing

- `asyncio_mode = "auto"` — async tests need no `@pytest.mark.asyncio` decorator.
- HTTP is mocked with `respx`. There is no `conftest.py`; tests mirror the `src/` layout.
- `get_settings()` is `@lru_cache`d — construct `Settings(_env_file=None, ...)` directly in tests.

## Gotchas

- The pipeline cursor only advances when `failed == 0`, so one permanently broken message re-runs
  its batch forever. Known limitation, tracked in @docs/improvement-checklist.md.
- First run records the cursor without summarizing existing mail; `--backfill` is the explicit
  opt-in and processes oldest-first.
- Delivery is at-least-once by design: a message is marked processed only after Telegram accepts
  it, so a crash at that boundary can repeat one notification.
- `.env`, `credentials/`, `data/`, and `config/assistant.toml` are gitignored and live untracked on
  the VPS. The deploy script uses `git reset --hard`, never a re-clone, to preserve them.
- Telegram user-facing strings are Vietnamese; the rest of the codebase is English.

## Repo etiquette

- Conventional Commits, lowercase, imperative, scoped to the layer or area:
  `feat(telegram):`, `fix(core):`, `ci(deploy):`, `docs(roadmap):`.
- **Pushing to `main` deploys to production.** `.github/workflows/deploy.yml` SSHes to the VPS and
  rebuilds. Run `uv run pytest` before pushing.
