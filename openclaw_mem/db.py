"""Database layer for openclaw-mem — SQLite + FTS5."""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = os.path.expanduser("~/.openclaw-mem/memory.db")

OBSERVATION_TYPES = (
    "observation", "rule", "contact", "event",
    "decision", "lesson", "state",
)

SOURCE_TYPES = (
    "manual", "daily-log", "session", "import", "synthesis",
)

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL DEFAULT 'observation',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    source_file TEXT,
    agent_id TEXT,
    channel TEXT,
    tags TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_by INTEGER REFERENCES observations(id),
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS session_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id TEXT,
    channel TEXT,
    peer TEXT,
    summary TEXT NOT NULL,
    key_decisions TEXT,
    key_actions TEXT,
    tools_used TEXT,
    started_at TEXT,
    ended_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS synthesis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL,
    input_date TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    output_observation_ids TEXT,
    error TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    observation_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source_path, source_hash)
);

CREATE INDEX IF NOT EXISTS idx_obs_type ON observations(type);
CREATE INDEX IF NOT EXISTS idx_obs_source ON observations(source);
CREATE INDEX IF NOT EXISTS idx_obs_agent ON observations(agent_id);
CREATE INDEX IF NOT EXISTS idx_obs_created ON observations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_obs_active ON observations(is_active);
CREATE INDEX IF NOT EXISTS idx_session_summaries_session ON session_summaries(session_id);
CREATE INDEX IF NOT EXISTS idx_session_summaries_agent ON session_summaries(agent_id);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
    title, content, tags,
    content=observations,
    content_rowid=id,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS observations_ai AFTER INSERT ON observations BEGIN
    INSERT INTO observations_fts(rowid, title, content, tags)
    VALUES (new.id, new.title, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS observations_ad AFTER DELETE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, title, content, tags)
    VALUES ('delete', old.id, old.title, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS observations_au AFTER UPDATE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, title, content, tags)
    VALUES ('delete', old.id, old.title, old.content, old.tags);
    INSERT INTO observations_fts(rowid, title, content, tags)
    VALUES (new.id, new.title, new.content, new.tags);
END;
"""


def _get_db_path() -> str:
    return os.environ.get("OPENCLAW_MEM_DB", DEFAULT_DB_PATH)


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a connection to the memory database."""
    path = db_path or _get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Create tables, FTS5 indexes, and triggers."""
    conn = get_connection(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.executescript(_FTS_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ── Write operations ────────────────────────────────────────────────────


def insert_observation(
    conn: sqlite3.Connection,
    title: str,
    content: str,
    type: str = "observation",
    source: str = "manual",
    source_file: Optional[str] = None,
    agent_id: Optional[str] = None,
    channel: Optional[str] = None,
    tags: Optional[str] = None,
    created_at: Optional[str] = None,
) -> int:
    """Insert a new observation. Returns the new row ID."""
    now = created_at or _now()
    cur = conn.execute(
        """INSERT INTO observations
           (type, title, content, source, source_file, agent_id, channel, tags, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (type, title, content, source, source_file, agent_id, channel, tags, now, now),
    )
    conn.commit()
    return cur.lastrowid


def update_observation(
    conn: sqlite3.Connection,
    obs_id: int,
    content: Optional[str] = None,
    title: Optional[str] = None,
    tags: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[int]:
    """Update an observation. If content changes, create a new version and supersede the old one.
    Returns the new observation ID if superseded, else None."""
    row = conn.execute("SELECT * FROM observations WHERE id = ?", (obs_id,)).fetchone()
    if not row:
        return None

    now = _now()

    if content is not None and content != row["content"]:
        # Create new version
        new_id = insert_observation(
            conn,
            title=title or row["title"],
            content=content,
            type=row["type"],
            source=row["source"],
            source_file=row["source_file"],
            agent_id=row["agent_id"],
            channel=row["channel"],
            tags=tags if tags is not None else row["tags"],
        )
        conn.execute(
            "UPDATE observations SET superseded_by = ?, is_active = 0, updated_at = ? WHERE id = ?",
            (new_id, now, obs_id),
        )
        conn.commit()
        return new_id

    # In-place update (no content change)
    updates = []
    params = []
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if tags is not None:
        updates.append("tags = ?")
        params.append(tags)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(int(is_active))
    if updates:
        updates.append("updated_at = ?")
        params.append(now)
        params.append(obs_id)
        conn.execute(
            f"UPDATE observations SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
    return None


# ── Read operations ─────────────────────────────────────────────────────


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    type: Optional[str] = None,
    limit: int = 20,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    tags: Optional[str] = None,
) -> list[dict]:
    """Full-text search using FTS5 with BM25 ranking."""
    # Sanitize query for FTS5: quote each token to avoid operator/column interpretation
    # e.g. "openclaw-mem plugin" → '"openclaw-mem" "plugin"'
    sanitized_tokens = []
    for token in query.split():
        escaped = token.replace('"', '""')
        sanitized_tokens.append(f'"{escaped}"')
    query = " ".join(sanitized_tokens)

    conditions = ["o.is_active = 1"]
    params = []

    if type:
        conditions.append("o.type = ?")
        params.append(type)
    if date_start:
        conditions.append("o.created_at >= ?")
        params.append(date_start)
    if date_end:
        conditions.append("o.created_at <= ?")
        params.append(date_end + " 23:59:59")
    if tags:
        for tag in tags.split(","):
            tag = tag.strip()
            if tag:
                conditions.append("o.tags LIKE ?")
                params.append(f"%{tag}%")

    where = " AND ".join(conditions)
    params_list = [query] + params + [min(limit, 100)]

    sql = f"""
        SELECT o.id, o.type, o.title, o.created_at, o.source, o.tags,
               rank
        FROM observations_fts fts
        JOIN observations o ON o.id = fts.rowid
        WHERE fts.observations_fts MATCH ?
          AND {where}
        ORDER BY rank
        LIMIT ?
    """

    rows = conn.execute(sql, params_list).fetchall()
    return [dict(r) for r in rows]


def get_timeline(
    conn: sqlite3.Connection,
    anchor_id: int,
    before: int = 3,
    after: int = 3,
) -> list[dict]:
    """Get observations chronologically around an anchor observation."""
    anchor = conn.execute(
        "SELECT created_at FROM observations WHERE id = ?", (anchor_id,)
    ).fetchone()
    if not anchor:
        return []

    anchor_time = anchor["created_at"]

    before_rows = conn.execute(
        """SELECT id, type, title, substr(content, 1, 200) as content_preview, created_at, source, tags
           FROM observations
           WHERE is_active = 1 AND created_at < ? AND id != ?
           ORDER BY created_at DESC LIMIT ?""",
        (anchor_time, anchor_id, before),
    ).fetchall()

    anchor_row = conn.execute(
        """SELECT id, type, title, substr(content, 1, 200) as content_preview, created_at, source, tags
           FROM observations WHERE id = ?""",
        (anchor_id,),
    ).fetchone()

    after_rows = conn.execute(
        """SELECT id, type, title, substr(content, 1, 200) as content_preview, created_at, source, tags
           FROM observations
           WHERE is_active = 1 AND created_at > ? AND id != ?
           ORDER BY created_at ASC LIMIT ?""",
        (anchor_time, anchor_id, after),
    ).fetchall()

    result = [dict(r) for r in reversed(before_rows)]
    if anchor_row:
        result.append(dict(anchor_row))
    result.extend(dict(r) for r in after_rows)
    return result


def get_observations(conn: sqlite3.Connection, ids: list[int]) -> list[dict]:
    """Batch fetch full observation content by IDs."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT id, type, title, content, source, source_file,
                   agent_id, channel, tags, created_at, updated_at,
                   superseded_by, is_active
            FROM observations WHERE id IN ({placeholders})
            ORDER BY created_at DESC""",
        ids,
    ).fetchall()
    return [dict(r) for r in rows]


def get_stats(conn: sqlite3.Connection) -> dict:
    """Get summary statistics about the memory database."""
    total = conn.execute(
        "SELECT COUNT(*) as c FROM observations WHERE is_active = 1"
    ).fetchone()["c"]

    by_type = conn.execute(
        """SELECT type, COUNT(*) as c FROM observations
           WHERE is_active = 1 GROUP BY type ORDER BY c DESC"""
    ).fetchall()

    date_range = conn.execute(
        """SELECT MIN(created_at) as earliest, MAX(created_at) as latest
           FROM observations WHERE is_active = 1"""
    ).fetchone()

    recent = conn.execute(
        """SELECT id, type, title, created_at FROM observations
           WHERE is_active = 1 ORDER BY created_at DESC LIMIT 5"""
    ).fetchall()

    summaries_count = conn.execute(
        "SELECT COUNT(*) as c FROM session_summaries"
    ).fetchone()["c"]

    return {
        "total_observations": total,
        "by_type": {r["type"]: r["c"] for r in by_type},
        "earliest": date_range["earliest"] if date_range else None,
        "latest": date_range["latest"] if date_range else None,
        "recent": [dict(r) for r in recent],
        "session_summaries": summaries_count,
    }


# ── Import tracking ─────────────────────────────────────────────────────


def is_imported(conn: sqlite3.Connection, source_path: str, source_hash: str) -> bool:
    """Check if a file has already been imported."""
    row = conn.execute(
        "SELECT 1 FROM import_log WHERE source_path = ? AND source_hash = ?",
        (source_path, source_hash),
    ).fetchone()
    return row is not None


def log_import(
    conn: sqlite3.Connection,
    source_path: str,
    source_hash: str,
    observation_count: int,
) -> None:
    """Record that a file was imported."""
    conn.execute(
        """INSERT OR IGNORE INTO import_log (source_path, source_hash, observation_count)
           VALUES (?, ?, ?)""",
        (source_path, source_hash, observation_count),
    )
    conn.commit()


if __name__ == "__main__":
    db_path = _get_db_path()
    print(f"Initializing database at {db_path}")
    init_db(db_path)
    print("Done.")
