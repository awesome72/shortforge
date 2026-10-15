"""sqlite3 연결 헬퍼. 표준 `with conn:`은 커밋만 하고 닫지 않으므로 둘 다 하는 것을 쓴다."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        with conn:  # 성공 시 commit, 예외 시 rollback
            yield conn
    finally:
        conn.close()
