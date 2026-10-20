"""작업별 LLM 라우팅 (고급 모드, D13).

지정한 작업(기본 S3 요인·S4 전략)만 고급 모드(유료) 어댑터로 보내고,
나머지는 기본(무료) 어댑터가 맡는다. 고급 모드가 실패하거나 하루 예산을 넘으면
기본 어댑터로 처리하고 알림을 남긴다 — 단계는 멈추지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.adapters.base import LLMAdapter, T
from app.spend import BudgetExceeded, SpendMeter


class RoutedLLM(LLMAdapter):
    def __init__(
        self,
        base: LLMAdapter,
        advanced: LLMAdapter,
        tasks: set[str],
        spend: SpendMeter,
        label: str,
    ) -> None:
        self.base = base
        self.advanced = advanced
        self.tasks = set(tasks)
        self.spend = spend
        self.label = label
        self.notices: list[str] = []

    @property
    def supports_images(self) -> bool:  # type: ignore[override]
        return self.base.supports_images

    @property
    def log(self):
        """기본 어댑터의 호출 기록 (측정 스크립트용)."""
        return getattr(self.base, "log", None)

    def routes_to_advanced(self, task: str) -> bool:
        return task in self.tasks

    async def generate_json(
        self, task: str, system: str, user: str, schema: type[T], *, images: Sequence[str] = ()
    ) -> T:
        if task in self.tasks and (not images or self.advanced.supports_images):
            try:
                self.spend.check()
                return await self.advanced.generate_json(task, system, user, schema, images=images)
            except BudgetExceeded as e:
                self._notice(f"{e} — 무료 경로로 처리했다")
            except Exception as e:  # noqa: BLE001 - 고급 모드 실패는 무료 경로로 넘긴다
                self._notice(f"고급 모드({self.label})가 실패해 무료 경로로 처리했다: {_short(e)}")
        return await self.base.generate_json(task, system, user, schema, images=images)

    def _notice(self, msg: str) -> None:
        if msg not in self.notices:
            self.notices.append(msg)

    def drain_notices(self) -> list[str]:
        out, self.notices = self.notices, []
        for adapter in (self.advanced, self.base):
            drain = getattr(adapter, "drain_notices", None)
            if drain:
                out.extend(m for m in drain() if m not in out)
        return out


def _short(e: Exception) -> str:
    msg = str(e).splitlines()[0] if str(e) else type(e).__name__
    return msg[:160]
