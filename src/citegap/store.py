"""Tiny SQLite store for report permalinks and re-audit deltas."""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Optional

from .report.model import Report
from .util import normalize_url


class Store:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS reports(
                id TEXT PRIMARY KEY, url_norm TEXT, url TEXT, query TEXT, created_at TEXT,
                ars REAL, svs REAL, body TEXT)""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_url ON reports(url_norm, created_at)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save(self, r: Report) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?,?,?,?,?,?)",
                      (r.id, normalize_url(r.url), r.url, r.query, r.created_at, r.ars.total, r.svs.total, r.model_dump_json()))

    def get(self, report_id: str) -> Optional[Report]:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT body FROM reports WHERE id=?", (report_id,)).fetchone()
        return Report.model_validate_json(row[0]) if row else None

    def previous_for(self, url: str, before: Optional[str] = None) -> Optional[Report]:
        q = "SELECT body FROM reports WHERE url_norm=?"
        args: list = [normalize_url(url)]
        if before:
            q += " AND created_at<?"
            args.append(before)
        q += " ORDER BY rowid DESC LIMIT 1"
        with self._lock, self._conn() as c:
            row = c.execute(q, args).fetchone()
        return Report.model_validate_json(row[0]) if row else None

    def recent(self, limit: int = 20) -> list[dict]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT id,url,query,created_at,ars,svs FROM reports ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(("id", "url", "query", "created_at", "ars", "svs"), r)) for r in rows]
