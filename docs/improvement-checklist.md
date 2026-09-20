# Improvement checklist

This checklist tracks improvements to Whisp's existing one-way
Gmail-to-OpenRouter-to-Telegram workflow. Interactive chat and inbound Telegram
webhooks are intentionally out of scope until the reliability work below is complete.

## P0 — Delivery correctness

### Durable message discovery

- [ ] Add a regression test covering more Gmail changes than
  `max_messages_per_run`.
- [ ] Add a durable pending-message table with a unique provider message ID.
- [ ] Persist all discovered message IDs before advancing the Gmail history cursor.
- [ ] Process at most `max_messages_per_run` pending records per run without losing
  the remaining records.
- [ ] Make discovery idempotent when the same Gmail history range is fetched again.
- [ ] Report discovered, queued, processed, skipped, and pending counts separately.

Acceptance criteria:

- A run that discovers 100 messages with a processing limit of 25 eventually processes
  all 100 messages across multiple runs.
- Restarting Whisp after discovery but before delivery does not lose queued messages.
- Re-reading a Gmail history range does not create duplicate queue records.

### Retry and dead-letter handling

- [ ] Track attempt count, last error, and next retry time per pending message.
- [ ] Classify retryable provider failures separately from permanent failures.
- [ ] Apply exponential backoff with jitter to retryable failures.
- [ ] Move a repeatedly failing message to a dead-letter state after a configurable
  attempt limit.
- [ ] Ensure one permanently failing email cannot block newer messages.
- [ ] Add a safe way to retry a dead-letter message manually.

Acceptance criteria:

- Temporary failures are retried without polling the provider continuously.
- A permanent failure becomes visible and does not prevent later email delivery.
- Restarting the process preserves attempt and retry state.

### Gmail cursor recovery

- [ ] Add tests for an expired Gmail history cursor.
- [ ] On expiration, backfill a configurable recent time window before recording the
  current cursor.
- [ ] Deduplicate recovered messages against queued and processed records.
- [ ] Record recovery counts and the cursor reset in run status.

Acceptance criteria:

- Recoverable messages received during a cursor gap are not silently skipped.
- Cursor recovery cannot create duplicate Telegram notifications.

## P0 — Secret safety

### Sanitize provider failures

- [ ] Wrap Telegram HTTP failures in a provider exception that does not contain the bot
  token or request URL.
- [ ] Sanitize errors before writing them to logs or SQLite.
- [ ] Review Gmail and OpenRouter error paths for credentials or sensitive payloads.
- [ ] Add tests asserting that known secrets never appear in logged or stored errors.

Acceptance criteria:

- Telegram tokens, API keys, OAuth tokens, and complete email bodies do not appear in
  application logs or stored error fields.
- Operators still receive an actionable provider name, status code, and safe error
  summary.

## P1 — Provider resilience

### Shared retry policy

- [ ] Introduce a shared retry policy for Gmail, OpenRouter, and Telegram clients.
- [ ] Retry connection failures, timeouts, rate limits, and selected server errors.
- [ ] Respect `Retry-After` when a provider supplies it.
- [ ] Do not retry authentication failures or invalid requests indefinitely.
- [ ] Make retry counts and HTTP timeouts configurable.
- [ ] Add deterministic retry tests without real sleeps.

Acceptance criteria:

- Each provider has explicit, tested retry behavior.
- Rate limiting does not cause a tight retry loop.
- Permanent configuration errors fail quickly with a safe diagnostic.

### Health and operational status

- [ ] Keep `/healthz` as a lightweight process health check.
- [ ] Add `/readyz` for cached provider and runtime readiness.
- [ ] Extend `/status` with last successful poll, duration, pending count, retry count,
  dead-letter count, and last sanitized failure.
- [ ] Track provider check timestamps rather than calling external providers from every
  health request.
- [ ] Add tests for health, readiness, and status responses.

Acceptance criteria:

- An operator can distinguish a running process from a working email pipeline.
- Status endpoints do not expose credentials, email bodies, or private provider URLs.

## P1 — Notification quality

### Structured processing result

- [ ] Replace the processor's raw string result with a typed result containing summary,
  priority, notification decision, and reason.
- [ ] Validate model output and fall back safely when structured output is invalid.
- [ ] Initially default to notifying rather than silently dropping uncertain results.
- [ ] Store non-sensitive decision metadata for evaluation.
- [ ] Add fixtures for urgent, normal, promotional, suspicious, and irrelevant email.

Acceptance criteria:

- Downstream output code does not need to parse model prose to understand priority.
- Invalid model output cannot silently suppress an email.

### Telegram presentation

- [ ] Replace the raw Gmail URL with an inline "Open email" URL button if it can be
  implemented without enabling inbound bot interactions.
- [ ] Represent priority consistently without excessive formatting.
- [ ] Decide whether long responses should be truncated or split, then test the chosen
  behavior at Telegram's message limit.
- [ ] Track processing success separately from Telegram delivery success.

Acceptance criteria:

- Notifications remain readable, safe from markup injection, and within Telegram API
  limits.
- A delivery failure can be retried without calling the model again unnecessarily.

## P2 — Email content quality

### MIME and HTML extraction

- [ ] Replace regex-only HTML stripping with a real HTML parser.
- [ ] Handle nested multipart alternatives without duplicate content.
- [ ] Support textual Gmail parts represented by an attachment ID.
- [ ] Remove common quoted replies, signatures, tracking text, and unsubscribe footers.
- [ ] Normalize whitespace and Unicode consistently.
- [ ] Mark truncated messages and truncate on meaningful boundaries where possible.
- [ ] Add fixtures for newsletters, reply chains, malformed HTML, and mixed-language
  messages.

Acceptance criteria:

- The model receives the human-readable message content without common duplicate or
  boilerplate sections.
- Parser failures degrade to a safe snippet rather than failing the complete pipeline.

## P2 — Cost, data, and maintenance

### Usage visibility

- [ ] Record model name, latency, token usage, truncation state, and estimated cost when
  available.
- [ ] Add aggregate usage information to the CLI status output.
- [ ] Add configurable per-run and daily processing safeguards.

### Database lifecycle

- [ ] Add explicit schema versioning and ordered migrations.
- [ ] Add retention settings for run history and processed-message metadata.
- [ ] Add `whisp prune` and database integrity-check commands.
- [ ] Document backup, restore, retention, and locally stored data.
- [ ] Test upgrades from every released schema version.

Acceptance criteria:

- Existing installations can upgrade without recreating the database.
- Database growth is bounded by documented retention settings.
- Backup and restore procedures preserve cursor and delivery state.

## Recommended execution order

- [ ] 1. Add the high-volume Gmail regression test.
- [ ] 2. Implement the durable pending-message queue.
- [ ] 3. Add retry, backoff, and dead-letter behavior.
- [ ] 4. Sanitize provider errors and add secret-leak tests.
- [ ] 5. Improve readiness and operational status.
- [ ] 6. Introduce structured processing results.
- [ ] 7. Improve MIME and HTML extraction.
- [ ] 8. Add usage, migration, retention, and maintenance tooling.
- [ ] 9. Reassess readiness for interactive Telegram chat and webhooks.
