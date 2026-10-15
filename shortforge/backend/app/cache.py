"""TTL이 있는 JSON 키-값 캐시 (SQLite). YouTube 응답을 24시간 보관해 쿼터를 아낀다."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.db import connect


class Cache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                " key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL)"
            )

    def _conn(self):
        return connect(self.db_path)

    def get(self, key: str) -> Any | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT value FROM cache WHERE key = ? AND expires_at > ?", (key, time.time())
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        if not keys:
            return {}
        out: dict[str, Any] = {}
        with self._conn() as c:
            for i in range(0, len(keys), 500):  # SQLite 변수 개수 제한
                chunk = keys[i : i + 500]
                marks = ",".join("?" * len(chunk))
                rows = c.execute(
                    f"SELECT key, value FROM cache WHERE key IN ({marks}) AND expires_at > ?",
                    (*chunk, time.time()),
                ).fetchall()
                out.update({k: json.loads(v) for k, v in rows})
        return out

    def set(self, key: str, value: Any, ttl_sec: float) -> None:
        self.set_many({key: value}, ttl_sec)

    def set_many(self, items: dict[str, Any], ttl_sec: float) -> None:
        expires = time.time() + ttl_sec
        with self._conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO cache(key, value, expires_at) VALUES (?, ?, ?)",
                [
                    (k, json.dumps(v, ensure_ascii=False, default=str), expires)
                    for k, v in items.items()
                ],
            )

    def purge_expired(self) -> int:
        with self._conn() as c:
            return c.execute("DELETE FROM cache WHERE expires_at <= ?", (time.time(),)).rowcount
