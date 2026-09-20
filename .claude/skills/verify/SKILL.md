---
name: verify
description: Run the project's lint, format and test checks (ruff + pytest) and report what failed. Use before committing or pushing, since pushing to main deploys to production.
---

Run the full check suite for this repo and report the result.

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Run all three even if an earlier one fails, so the user sees every problem at once.

Reporting:

- If everything passes, say so in one line with the test count.
- If something fails, show the relevant output — the failing test names and assertion
  diffs, or the ruff rule codes and file:line. Do not paste the entire log.
- `ruff format --check` failures list files that would be reformatted; offer to run
  `uv run ruff format .` to fix them.
- Do not fix failures unless the user asks. Report first.

These are the same checks `.github/workflows/test.yml` runs in CI, and a push to `main`
is blocked from deploying if they fail.
