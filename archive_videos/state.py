"""SQLite state database for tracking per-video workflow progress."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import osxphotos  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS video_state (
    uuid TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    state TEXT NOT NULL,
    original_path TEXT,
    compressed_path TEXT,
    s3_key TEXT,
    s3_etag TEXT,
    sidecar_path TEXT,
    error_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class State(str, Enum):
    DISCOVERED = "DISCOVERED"
    EXPORTED = "EXPORTED"
    COMPRESSED = "COMPRESSED"
    UPLOADED = "UPLOADED"
    VERIFIED = "VERIFIED"
    DELETED = "DELETED"
    IMPORTED = "IMPORTED"
    METADATA_RESTORED = "METADATA_RESTORED"
    DONE = "DONE"
    ERROR = "ERROR"


@dataclass
class VideoRecord:
    uuid: str
    filename: str
    state: State
    original_path: str | None = None
    compressed_path: str | None = None
    s3_key: str | None = None
    s3_etag: str | None = None
    sidecar_path: str | None = None
    error_log: str | None = None


class StateDB:
    """SQLite-backed state tracker with resume support."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_or_update(self, record: VideoRecord) -> None:
        """Upsert a video record."""
        sql = """
        INSERT INTO video_state (
            uuid, filename, state, original_path, compressed_path,
            s3_key, s3_etag, sidecar_path, error_log, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(uuid) DO UPDATE SET
            filename = excluded.filename,
            state = excluded.state,
            original_path = excluded.original_path,
            compressed_path = excluded.compressed_path,
            s3_key = excluded.s3_key,
            s3_etag = excluded.s3_etag,
            sidecar_path = excluded.sidecar_path,
            error_log = excluded.error_log,
            updated_at = CURRENT_TIMESTAMP
        """
        with self._conn() as conn:
            conn.execute(
                sql,
                (
                    record.uuid,
                    record.filename,
                    record.state.value,
                    record.original_path,
                    record.compressed_path,
                    record.s3_key,
                    record.s3_etag,
                    record.sidecar_path,
                    record.error_log,
                ),
            )
            conn.commit()
        logger.debug("State updated: %s → %s", record.uuid, record.state.value)

    def get(self, uuid: str) -> VideoRecord | None:
        """Retrieve a video record by UUID."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM video_state WHERE uuid = ?", (uuid,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_pending(self) -> list[VideoRecord]:
        """Return all records not yet in DONE state."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM video_state WHERE state != ?", (State.DONE.value,)
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_by_state(self, state: State) -> list[VideoRecord]:
        """Return all records in a specific state."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM video_state WHERE state = ?", (state.value,)
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def reset_to(self, uuid: str, state: State) -> None:
        """Reset a record to a specific state (useful for retry)."""
        self.insert_or_update(VideoRecord(uuid=uuid, filename="", state=state))

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> VideoRecord:
        kwargs = {
            k: row[k] for k in row.keys() if k not in ("created_at", "updated_at")
        }
        kwargs["state"] = State(kwargs["state"])
        return VideoRecord(**kwargs)


def new_record_from_asset(asset: osxphotos.PhotoInfo, state: State = State.DISCOVERED) -> VideoRecord:
    """Create a fresh VideoRecord from a discovered asset."""
    return VideoRecord(
        uuid=asset.uuid,
        filename=asset.filename,
        state=state,
    )
