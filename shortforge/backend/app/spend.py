"""고급 모드(D13) 비용 미터. 유료 LLM 응답의 토큰 사용량 × 가격표로 하루 사용액을 센다.

- 날짜는 UTC 기준이다. 하루 예산(ADVANCED_DAILY_BUDGET_USD)을 넘으면 고급 모드를 멈추고
  무료 경로로 돌아간다.
- 가격표에 없는 모델은 예산을 지킬 수 없으므로 쓰지 않는다(설정 단계에서 거절).
- 가격은 1M 토큰당 USD (2026-10 기준). 바뀌면 여기만 고친다.
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
        "claude-sonnet-5-5": Price("Claude Sonnet 5.5 (추천: 품질·속도·비용 균형)", 2.00, 10.00),
        "claude-haiku-5-5": Price("Claude Haiku 5.5 (가장 저렴)", 0.10, 0.50),
    },
    # OpenAI 가격: OpenRouter 공개 모델 목록의 OpenAI 모델 가격(통과 요금)으로 확인 (2026-10-20)
    "openai": {
        "gpt-5.6-sol": Price("GPT-5.6 Sol (가장 높은 품질)", 4.00, 20.00),
        "gpt-5.6-terra": Price("GPT-5.6 Terra (품질·비용 균형)", 2.00, 12.00),
        "gpt-5.6-luna": Price("GPT-5.6 Luna (가장 저렴)", 0.20, 1.20),
    },
    # OpenRouter: 키 하나로 여러 회사 모델. 구조화 출력·이미지를 지원하는 모델만 고른다
    # (openrouter.ai/api/v1/models의 supported_parameters, 2026-10-20).
    # 실제 청구액은 응답의 usage.cost로 기록한다
    "openrouter": {
        "anthropic/claude-opus-5.5": Price("Claude Opus 5.5 (OpenRouter)", 4.00, 20.00),
        "anthropic/claude-sonnet-5.5": Price("Claude Sonnet 5.5 (OpenRouter, 추천)", 2.00, 10.00),
        "anthropic/claude-haiku-5.5": Price("Claude Haiku 5.5 (OpenRouter)", 0.10, 0.50),
        "openai/gpt-5.6-sol": Price("GPT-5.6 Sol (OpenRouter)", 4.00, 20.00),
        "openai/gpt-5.6-terra": Price("GPT-5.6 Terra (OpenRouter)", 2.00, 12.00),
        "openai/gpt-5.6-luna": Price("GPT-5.6 Luna (OpenRouter)", 0.20, 1.20),
    },
}
# 기본 모델 (D13 실측 2026-10-20): Claude Sonnet 5.5가 Opus 5.5보다 2배 빠르고 비용은 40%이면서
# Gate를 통과하고 결과 대사가 구체적이었다. OpenAI는 Terra가 재생성 3회로 근거가 약해 Sol로 둔다
DEFAULT_MODEL = {
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-5.6-sol",
    "openrouter": "anthropic/claude-sonnet-5.5",
}
PROVIDER_LABEL = {"anthropic": "Anthropic", "openai": "OpenAI", "openrouter": "OpenRouter"}


# 영상 만들기(D19): Hugging Face → fal의 LTX-2 distilled. 메가픽셀당 $0.0008
# (fal 모델 페이지, 2026-10-31). 704×1248 한 프레임 = 0.8786MP, 25fps라 1초에 약 $0.018.
# 같은 곳의 Wan 2.2 A14B는 720p 1초에 $0.08이다. 값이 바뀌면 여기만 고친다
# fal은 메가픽셀을 올림해 청구해 호출당 최대 $0.0008 더 나갈 수 있다


@dataclass(frozen=True)
class VideoModel:
    hf_id: str
    provider_id: str
    label: str
    fps: int
    width: int
    height: int
    usd_per_mp: float

    @property
    def usd_per_frame(self) -> float:
        return self.width * self.height / 1_000_000 * self.usd_per_mp

    @property
    def usd_per_sec(self) -> float:
        return self.usd_per_frame * self.fps


VIDEO_PROVIDER = "huggingface"
VIDEO_MODEL = VideoModel(
    "Lightricks/LTX-2",
    "fal-ai/ltx-2-19b/distilled/image-to-video",
    "LTX-2 (이미지 → 영상)",
    fps=25,
    width=704,
    height=1248,
    usd_per_mp=0.0008,
)


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
    """provider를 주면 그 제공자만 센다(영상 만들기). 없으면 고급 모드 LLM 사용액만 센다."""

    def __init__(self, db_path: Path, daily_budget_usd: float, provider: str | None = None) -> None:
        self.db_path = Path(db_path)
        self.daily_budget_usd = daily_budget_usd
        self.provider = provider
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
        where = "provider = ?" if self.provider else "provider != ?"
        with connect(self.db_path) as c:
            row = c.execute(
                f"SELECT COALESCE(SUM(usd), 0) FROM spend_log WHERE day = ? AND {where}",
                (day or utc_today(), self.provider or VIDEO_PROVIDER),
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

    def check_cost(self, cost: float) -> None:
        """값을 미리 아는 호출(영상 만들기)용: 이번 호출까지 더해 예산을 넘으면 BudgetExceeded."""
        used = self.used()
        if used + cost > self.daily_budget_usd:
            raise BudgetExceeded(
                f"오늘 영상 예산 ${self.daily_budget_usd:.2f}을 넘어요 (쓴 돈 ${used:.2f}, "
                f"이번 장면 ${cost:.2f}). 설정에서 예산을 늘리거나 오전 9시 뒤에 다시 해 주세요."
            )

    def record(
        self, provider: str, model: str, task: str, input_tokens: int, output_tokens: int
    ) -> float:
        usd = cost_usd(provider, model, input_tokens, output_tokens)
        return self.record_usd(provider, model, task, input_tokens, output_tokens, usd)

    def record_usd(
        self, provider: str, model: str, task: str, input_tokens: int, output_tokens: int,
        usd: float,
    ) -> float:  # fmt: skip
        """제공자가 알려 준 실제 청구액으로 기록한다 (OpenRouter usage.cost)."""
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
