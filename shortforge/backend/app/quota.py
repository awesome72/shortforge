"""YouTube Data API 쿼터 미터 (PROJECT_PROMPT §2-4, F-2.4).

- 쿼터는 태평양 시간(PT) 자정에 초기화되므로 날짜도 PT 기준으로 센다.
- search.list(100 units)는 일 사용량이 daily_limit(기본 8,000)를 넘게 되면 막는다.
- 1 unit짜리 조회(videos/channels/commentThreads)는 실제 일 한도(10,000)까지 허용한다.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.db import connect

PT = ZoneInfo("America/Los_Angeles")
HARD_LIMIT = 10_000

COST = {"search": 100, "videos": 1, "channels": 1, "commentThreads": 1, "i18nLanguages": 1}


class QuotaExceeded(RuntimeError):
    pass


def pt_today() -> date:
    return datetime.now(PT).date()


class QuotaMeter:
    def __init__(self, db_path: Path, daily_limit: int = 8000) -> None:
        self.db_path = Path(db_path)
        self.daily_limit = daily_limit
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS quota_log ("
                " id INTEGER PRIMARY KEY, day TEXT NOT NULL, at TEXT NOT NULL,"
                " method TEXT NOT NULL, units INTEGER NOT NULL)"
            )
            c.execute("CREATE INDEX IF NOT EXISTS quota_log_day ON quota_log(day)")

    def _conn(self):
        return connect(self.db_path)

    def used(self, day: date | None = None) -> int:
        day = day or pt_today()
        with self._conn() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(units), 0) FROM quota_log WHERE day = ?", (day.isoformat(),)
            ).fetchone()
        return int(row[0])

    def check(self, method: str) -> None:
        """호출 전에 부른다. 한도를 넘게 되면 QuotaExceeded."""
        units = COST[method]
        used = self.used()
        limit = self.daily_limit if method == "search" else HARD_LIMIT
        if used + units > limit:
            raise QuotaExceeded(
                f"오늘(PT {pt_today()}) YouTube 쿼터 {used}/{limit} units 사용 — "
                f"{method}({units} units)를 막았다. PT 자정에 초기화된다"
            )

    def record(self, method: str) -> None:
        """호출 후에 부른다 (실패한 호출도 쿼터를 쓰므로 응답과 무관하게 기록)."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO quota_log(day, at, method, units) VALUES (?, ?, ?, ?)",
                (pt_today().isoformat(), datetime.now(PT).isoformat(), method, COST[method]),
            )

    def summary(self) -> dict:
        used = self.used()
        return {
            "day_pt": pt_today().isoformat(),
            "used": used,
            "search_limit": self.daily_limit,
            "hard_limit": HARD_LIMIT,
            "search_blocked": used + COST["search"] > self.daily_limit,
        }
