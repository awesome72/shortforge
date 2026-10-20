"""고급 모드(D13) 비용 미터. 유료 LLM 응답의 토큰 사용량 × 가격표로 하루 사용액을 센다.

- 날짜는 UTC 기준이다. 하루 예산(ADVANCED_DAILY_BUDGET_USD)을 넘으면 고급 모드를 멈추고
  무료 경로로 돌아간다.
- 가격표에 없는 모델은 예산을 지킬 수 없으므로 쓰지 않는다(설정 단계에서 거절).
- 가격은 1M 토큰당 USD (Anthropic 공식 가격, 2026-10 기준). 바뀌면 여기만 고친다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.db import connect


@dataclass(frozen=True)
class Price:
    label: str
    input: float  # USD / 1M 입력 토큰
    output: float  # USD / 1M 출력 토큰


PRICES: dict[str, dict[str, Price]] = {
    "anthropic": {
        "claude-opus-5-5": Price("Claude Opus 5.5 (가장 높은 품질)", 4.00, 20.00),
        "claude-sonnet-5-5": Price("Claude Sonnet 5.5 (품질·비용 균형)", 2.00, 10.00),
        "claude-haiku-5-5": Price("Claude Haiku 5.5 (가장 저렴)", 0.10, 0.50),
    },
}
DEFAULT_MODEL = {"anthropic": "claude-opus-5-5"}


class BudgetExceeded(RuntimeError):
    pass


def price_for(provider: str, model: str) -> Price | None:
    return PRICES.get(provider, {}).get(model)


def cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    p = price_for(provider, model)
    if p is None:
        return 0.0
    return (input_tokens * p.input + output_tokens * p.output) / 1_000_000


def utc_today() -> str:
    return datetime.now(UTC).date().isoformat()


class SpendMeter:
    def __init__(self, db_path: Path, daily_budget_usd: float) -> None:
        self.db_path = Path(db_path)
        self.daily_budget_usd = daily_budget_usd
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect(self.db_path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS spend_log ("
                " id INTEGER PRIMARY KEY, day TEXT NOT NULL, at TEXT NOT NULL,"
                " provider TEXT NOT NULL, model TEXT NOT NULL, task TEXT NOT NULL,"
                " input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, usd REAL NOT NULL)"
            )
            c.execute("CREATE INDEX IF NOT EXISTS spend_log_day ON spend_log(day)")

    def used(self, day: str | None = None) -> float:
        with connect(self.db_path) as c:
            row = c.execute(
                "SELECT COALESCE(SUM(usd), 0) FROM spend_log WHERE day = ?", (day or utc_today(),)
            ).fetchone()
        return float(row[0])

    def check(self) -> None:
        """호출 전에 부른다. 오늘 예산을 다 썼으면 BudgetExceeded."""
        used = self.used()
        if used >= self.daily_budget_usd:
            raise BudgetExceeded(
                f"고급 모드 오늘 예산 ${self.daily_budget_usd:.2f}을 다 썼다 (${used:.2f}) — "
                "UTC 자정(한국 오전 9시)에 초기화된다"
            )

    def record(
        self, provider: str, model: str, task: str, input_tokens: int, output_tokens: int
    ) -> float:
        usd = cost_usd(provider, model, input_tokens, output_tokens)
        with connect(self.db_path) as c:
            c.execute(
                "INSERT INTO spend_log(day, at, provider, model, task, input_tokens,"
                " output_tokens, usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    utc_today(), datetime.now(UTC).isoformat(), provider, model, task,
                    input_tokens, output_tokens, usd,
                ),
            )  # fmt: skip
        return usd

    def summary(self) -> dict:
        return {
            "day_utc": utc_today(),
            "used_usd": round(self.used(), 4),
            "budget_usd": self.daily_budget_usd,
        }
