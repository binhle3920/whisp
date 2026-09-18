import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from whisp.core.models import EmailMessage


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

    def start_run(self) -> int:
        with self._connect() as db:
            cursor = db.execute("INSERT INTO runs DEFAULT VALUES")
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
                UPDATE runs SET finished_at=datetime('now'), discovered=?, notified=?,
                    skipped=?, failed=?, error=? WHERE id=?
                """,
                (discovered, notified, skipped, failed, error, run_id),
            )

    def status(self) -> dict[str, object]:
        with self._connect() as db:
            run = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            count = db.execute("SELECT COUNT(*) AS count FROM processed_messages").fetchone()
        return {
            "history_id": self.get("history_id"),
            "processed_messages": int(count["count"]),
            "last_run": dict(run) if run else None,
        }

