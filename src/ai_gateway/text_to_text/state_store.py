from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import CallResult, InputRecord


class StateStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS records (
              record_key TEXT PRIMARY KEY, source_row INTEGER NOT NULL, input_hash TEXT NOT NULL,
              status TEXT NOT NULL, raw_text TEXT NOT NULL DEFAULT '', parsed_json TEXT NOT NULL DEFAULT '{}',
              model TEXT NOT NULL DEFAULT '', request_id TEXT, latency_ms INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
              error_category TEXT, error_message TEXT, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (
              id INTEGER PRIMARY KEY AUTOINCREMENT, record_key TEXT NOT NULL, input_hash TEXT NOT NULL,
              attempt INTEGER NOT NULL, status TEXT NOT NULL, request_id TEXT, latency_ms INTEGER,
              error_category TEXT, error_message TEXT, created_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def get(self, record_key: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM records WHERE record_key=?", (record_key,)).fetchone()
        return self._decode(row) if row else None

    def save(self, result: CallResult) -> None:
        self.connection.execute(
            """INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(record_key) DO UPDATE SET source_row=excluded.source_row,input_hash=excluded.input_hash,
            status=excluded.status,raw_text=excluded.raw_text,parsed_json=excluded.parsed_json,model=excluded.model,
            request_id=excluded.request_id,latency_ms=excluded.latency_ms,attempts=excluded.attempts,
            error_category=excluded.error_category,error_message=excluded.error_message,updated_at=excluded.updated_at""",
            (result.record_key, result.source_row, result.input_hash, result.status, result.raw_text,
             json.dumps(result.parsed, ensure_ascii=False), result.model, result.request_id, result.latency_ms,
             result.attempts, result.error_category, result.error_message, result.updated_at),
        )
        self.connection.execute(
            "INSERT INTO attempts(record_key,input_hash,attempt,status,request_id,latency_ms,error_category,error_message,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (result.record_key, result.input_hash, result.attempts, result.status, result.request_id,
             result.latency_ms, result.error_category, result.error_message, result.updated_at),
        )
        self.connection.commit()

    def stage(self, record: InputRecord, status: str = "pending") -> None:
        """Record newly discovered or changed input without creating an API attempt."""
        self.connection.execute(
            """INSERT INTO records(record_key,source_row,input_hash,status,updated_at) VALUES(?,?,?,?,?)
            ON CONFLICT(record_key) DO UPDATE SET source_row=excluded.source_row,input_hash=excluded.input_hash,
            status=excluded.status,raw_text='',parsed_json='{}',model='',request_id=NULL,latency_ms=NULL,
            attempts=0,error_category=NULL,error_message=NULL,updated_at=excluded.updated_at""",
            (record.record_key, record.source_row, record.input_hash, status, _now()),
        )
        self.connection.commit()

    def all(self) -> list[dict[str, Any]]:
        return [self._decode(row) for row in self.connection.execute("SELECT * FROM records ORDER BY source_row")]

    def close(self) -> None:
        self.connection.close()

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["parsed"] = json.loads(value.pop("parsed_json") or "{}")
        return value


def _now() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")
