"""SQLite catalog that tracks every match from discovery to parsed record."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

# found -> url -> downloaded -> parsed
# side exits: skipped (didn't qualify), expired (replay gone), failed (error, may retry)
STATUSES = ("found", "url", "downloaded", "parsed", "skipped", "expired", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id      INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,
    status        TEXT NOT NULL,
    start_time    INTEGER,
    duration      INTEGER,
    patch         INTEGER,
    n_immortal    INTEGER,
    avg_mmr       REAL,
    replay_url    TEXT,
    raw_path      TEXT,
    reason        TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    updated_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS matches_status ON matches(status, source);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


class Catalog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---- writes
    def add_found(self, source: str, rows: Iterable[dict[str, Any]]) -> int:
        """Insert newly discovered matches. Returns how many were new."""
        now = int(time.time())
        cur = self.db.executemany(
            "INSERT OR IGNORE INTO matches(match_id, source, status, start_time, duration, updated_at)"
            " VALUES (?, ?, 'found', ?, ?, ?)",
            [(r["match_id"], source, r.get("start_time"), r.get("duration"), now) for r in rows],
        )
        self.db.commit()
        return cur.rowcount

    def upsert(self, match_id: int, source: str, status: str, **fields: Any) -> None:
        assert status in STATUSES, status
        fields = {"status": status, "updated_at": int(time.time()), **fields}
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{k}=excluded.{k}" for k in fields)
        self.db.execute(
            f"INSERT INTO matches(match_id, source, {cols}) VALUES (?, ?, {marks})"
            f" ON CONFLICT(match_id) DO UPDATE SET {updates}",
            (match_id, source, *fields.values()),
        )
        self.db.commit()

    def set_status(self, match_id: int, status: str, **fields: Any) -> None:
        assert status in STATUSES, status
        fields = {"status": status, "updated_at": int(time.time()), **fields}
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE matches SET {sets} WHERE match_id=?", (*fields.values(), match_id))
        self.db.commit()

    def bump_attempts(self, match_id: int) -> int:
        self.db.execute("UPDATE matches SET attempts = attempts + 1 WHERE match_id=?", (match_id,))
        self.db.commit()
        return self.get(match_id)["attempts"]

    # ---- reads
    def get(self, match_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM matches WHERE match_id=?", (match_id,)).fetchone()

    def with_status(self, status: str, source: str | None = None, limit: int = 100,
                    newest_first: bool = True) -> list[sqlite3.Row]:
        order = "DESC" if newest_first else "ASC"
        if source:
            q = f"SELECT * FROM matches WHERE status=? AND source=? ORDER BY match_id {order} LIMIT ?"
            return self.db.execute(q, (status, source, limit)).fetchall()
        q = f"SELECT * FROM matches WHERE status=? ORDER BY match_id {order} LIMIT ?"
        return self.db.execute(q, (status, limit)).fetchall()

    def count(self, status: str | None = None, source: str | None = None) -> int:
        q, args = "SELECT COUNT(*) FROM matches WHERE 1=1", []
        if status:
            q += " AND status=?"
            args.append(status)
        if source:
            q += " AND source=?"
            args.append(source)
        return self.db.execute(q, args).fetchone()[0]

    def summary(self) -> list[tuple[str, str, int]]:
        return [tuple(r) for r in self.db.execute(
            "SELECT source, status, COUNT(*) FROM matches GROUP BY source, status ORDER BY source, status")]

    def parsed_ids(self, source: str | None = None) -> list[int]:
        if source:
            rows = self.db.execute("SELECT match_id FROM matches WHERE status='parsed' AND source=?", (source,))
        else:
            rows = self.db.execute("SELECT match_id FROM matches WHERE status='parsed'")
        return [r[0] for r in rows]

    def oldest_found_id(self, source: str) -> int | None:
        r = self.db.execute("SELECT MIN(match_id) FROM matches WHERE source=?", (source,)).fetchone()
        return r[0] if r and r[0] is not None else None

    # ---- key/value
    def kv_get(self, key: str, default: str | None = None) -> str | None:
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def kv_set(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))
        self.db.commit()
