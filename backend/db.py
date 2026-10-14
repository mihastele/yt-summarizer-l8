"""SQLite store keyed by (canonical_url, length) with capped version history."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    video_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    length TEXT NOT NULL,
    summary TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    transcript_chars INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_summaries_pair ON summaries(url, length, id DESC);
CREATE INDEX IF NOT EXISTS idx_summaries_recent ON summaries(created_at DESC);
"""

_lock = threading.Lock()
_db_path: str | None = None


def init_db(database_path: str) -> None:
    global _db_path
    _db_path = database_path
    path = Path(database_path)
    if str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.commit()
    finally:
        conn.close()


def _connect() -> sqlite3.Connection:
    if not _db_path:
        raise RuntimeError("Database not initialised; call init_db() first")
    conn = sqlite3.connect(_db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def list_summaries(url: str, length: str) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM summaries WHERE url = ? AND length = ? ORDER BY id DESC",
            (url, length),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def add_summary(
    *,
    url: str,
    video_id: str,
    title: str,
    length: str,
    summary: str,
    model: str,
    transcript_chars: int,
    max_versions: int,
) -> dict[str, Any]:
    """Insert a new version, evict oldest past max_versions, return full list (newest first)."""
    created_at = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """INSERT INTO summaries (url, video_id, title, length, summary, model, transcript_chars, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (url, video_id, title, length, summary, model, transcript_chars, created_at),
            )
            new_id = cur.lastrowid
            if max_versions > 0:
                conn.execute(
                    """DELETE FROM summaries WHERE url = ? AND length = ? AND id NOT IN (
                           SELECT id FROM summaries WHERE url = ? AND length = ? ORDER BY id DESC LIMIT ?
                       )""",
                    (url, length, url, length, max_versions),
                )
            conn.commit()
            rows = conn.execute(
                "SELECT * FROM summaries WHERE url = ? AND length = ? ORDER BY id DESC",
                (url, length),
            ).fetchall()
            result = [_row_to_dict(r) for r in rows]
            assert any(r["id"] == new_id for r in result)
            return result
        finally:
            conn.close()


def delete_summary(summary_id: int) -> bool:
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM summaries WHERE id = ?", (summary_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def recent_pairs(limit: int = 20) -> list[dict[str, Any]]:
    """Most recent summary per (url, length) pair for history display."""
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT s.* FROM summaries s
               INNER JOIN (
                   SELECT url, length, MAX(id) AS max_id FROM summaries GROUP BY url, length
               ) latest ON s.id = latest.max_id
               ORDER BY s.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = _row_to_dict(r)
            count = conn.execute(
                "SELECT COUNT(*) FROM summaries WHERE url = ? AND length = ?",
                (d["url"], d["length"]),
            ).fetchone()[0]
            d["version_count"] = count
            out.append(d)
        return out
    finally:
        conn.close()
