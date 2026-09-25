import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from whisp.core.models import DigestItem, EmailMessage


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    processed_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL DEFAULT (datetime('now')),
                    finished_at TEXT,
                    discovered INTEGER NOT NULL DEFAULT 0,
                    notified INTEGER NOT NULL DEFAULT 0,
                    skipped INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS digest_queue (
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    summary TEXT,
                    queued_at TEXT NOT NULL DEFAULT (datetime('now')),
                    sent_at TEXT
                );
                """
            )

    def get(self, key: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set(self, key: str, value: str) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO kv(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')
                """,
                (key, value),
            )

    def is_processed(self, message_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM processed_messages WHERE message_id = ?", (message_id,)
            ).fetchone()
        return row is not None

    def mark_processed(self, message: EmailMessage) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO processed_messages(message_id, subject, sender)
                VALUES (?, ?, ?)
                """,
                (message.id, message.subject, message.sender),
            )

    def queue_digest(self, message: EmailMessage, *, summary: str | None) -> None:
        # Queuing counts as processing: one transaction so a held message is never
        # re-fetched by a later run, nor recorded as processed without being queued.
        with self._connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO digest_queue(message_id, thread_id, sender, subject, summary)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message.id, message.thread_id, message.sender, message.subject, summary),
            )
            db.execute(
                """
                INSERT OR IGNORE INTO processed_messages(message_id, subject, sender)
                VALUES (?, ?, ?)
                """,
                (message.id, message.subject, message.sender),
            )

    def pending_digest(self) -> list[DigestItem]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT message_id, thread_id, sender, subject, summary FROM digest_queue
                WHERE sent_at IS NULL ORDER BY queued_at, rowid
                """
            ).fetchall()
        return [
            DigestItem(
                message_id=row["message_id"],
                thread_id=row["thread_id"],
                sender=row["sender"],
                subject=row["subject"],
                summary=row["summary"],
            )
            for row in rows
        ]

    def mark_digest_sent(self, message_ids: list[str]) -> None:
        sent_at = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.executemany(
                "UPDATE digest_queue SET sent_at = ? WHERE message_id = ?",
                [(sent_at, message_id) for message_id in message_ids],
            )

    def start_run(self) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO runs(started_at) VALUES (?)", (datetime.now(UTC).isoformat(),)
            )
            return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        discovered: int,
        notified: int,
        skipped: int,
        failed: int,
        error: str | None = None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE runs SET finished_at=?, discovered=?, notified=?,
                    skipped=?, failed=?, error=? WHERE id=?
                """,
                (
                    datetime.now(UTC).isoformat(),
                    discovered,
                    notified,
                    skipped,
                    failed,
                    error,
                    run_id,
                ),
            )

    def status(self) -> dict[str, object]:
        with self._connect() as db:
            run = db.execute(
                """
                SELECT *, CASE WHEN finished_at IS NULL THEN NULL ELSE
                    CAST((julianday(finished_at) - julianday(started_at)) * 86400000 AS INTEGER)
                    END AS duration_ms
                FROM runs ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            last_success = db.execute(
                """
                SELECT finished_at FROM runs
                WHERE finished_at IS NOT NULL AND failed = 0 AND error IS NULL
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            last_failure = db.execute(
                """
                SELECT finished_at, failed, error FROM runs
                WHERE failed > 0 OR error IS NOT NULL
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            count = db.execute("SELECT COUNT(*) AS count FROM processed_messages").fetchone()
            cursor = db.execute("SELECT value FROM kv WHERE key = 'history_id'").fetchone()
            digest = db.execute(
                "SELECT COUNT(*) AS count FROM digest_queue WHERE sent_at IS NULL"
            ).fetchone()
        return {
            "history_id": str(cursor["value"]) if cursor else None,
            "processed_messages": int(count["count"]),
            "digest_pending": int(digest["count"]),
            "last_run": dict(run) if run else None,
            "last_successful_poll_at": last_success["finished_at"] if last_success else None,
            "last_failure": dict(last_failure) if last_failure else None,
            "queue": {
                "available": False,
                "pending": 0,
                "retrying": 0,
                "dead_letter": 0,
            },
        }
