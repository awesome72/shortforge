"""Gemini 무료 등급 어댑터 (LLM_MODE=gemini, D3).

무료 등급 주의 (PRD §8): 분당·일일 호출 제한이 있고, 입력이 모델 개선에 쓰일 수 있으며,
상업적 이용에서 제외된다. 사업화 시점에는 Ollama로 전환한다.

일일 한도 (2026-10 실측): gemini-3.8-flash 무료 등급은 프로젝트·모델당 하루 20회
(GenerateRequestsPerDayPerProjectPerModel-FreeTier). 한도는 모델마다 따로 잡힌다. 그래서
- 품질이 중요한 작업(S3 요인, S4 전략)은 주 모델, 가벼운 작업(S1 키워드, S2 관련성, S6 연출)은
  경량 모델로 보내 하루 처리량을 늘린다.
- 주 모델의 일일 한도가 바닥나면 기다리지 않고 경량 모델로 넘긴다(알림을 남긴다).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable

from google import genai
from google.genai import errors, types

from app.adapters.llm.common import JSONLLMAdapter

RATE_LIMIT_WAITS = (10, 25, 60)  # 분당 한도(429)일 때 기다리는 초
SERVER_WAITS = (
    5,
    15,
    30,
)  # 503(과부하) 등 서버 오류일 때 기다리는 초. 2026-10 실측에서 3초×2회로는 부족했다
LIGHT_TASKS = frozenset({"s1_keywords", "s2_relevance", "s5_image_prompts", "s6_timeline"})
OVERLOAD_COOLDOWN_SEC = 600  # 과부하가 확인된 모델은 이 시간 동안 건너뛴다


class GeminiQuotaExhausted(RuntimeError):
    """오늘 무료 호출 한도를 다 썼다 (기다려도 풀리지 않는다)."""


def _daily_quota(e: errors.ClientError) -> tuple[bool, float | None]:
    """(일일 한도 초과인가, 초기화까지 남은 초)."""
    raw = json.dumps(e.details or {}, ensure_ascii=False)
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', raw)
    return "PerDay" in raw, float(m.group(1)) if m else None


class GeminiAdapter(JSONLLMAdapter):
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        light_model: str | None = None,
        light_tasks: frozenset[str] = LIGHT_TASKS,
        temperature: float = 0.4,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        client: genai.Client | None = None,
    ) -> None:
        super().__init__()
        if not api_key and client is None:
            raise RuntimeError(
                "GEMINI_API_KEY가 비어 있다 — shortforge/.env에 넣거나 LLM_MODE=ollama"
            )
        self.model = model
        self.light_model = light_model or model
        self.light_tasks = light_tasks
        self.temperature = temperature
        self._sleep = sleep
        self.client = client or genai.Client(api_key=api_key)
        self.exhausted: set[str] = set()  # 오늘 일일 한도를 다 쓴 모델
        self._overloaded_until: dict[str, float] = {}  # 모델 → 다시 시도해도 되는 시각

    def model_for(self, task: str) -> str:
        model = self.light_model if task in self.light_tasks else self.model
        unavailable = model in self.exhausted or self._overloaded(model)
        if unavailable and self.light_model not in self.exhausted:
            return self.light_model
        return model

    def _overloaded(self, model: str) -> bool:
        return time.monotonic() < self._overloaded_until.get(model, 0)

    def _notice(self, msg: str) -> None:
        if msg not in self.notices:  # 재시도·재생성마다 같은 알림이 쌓이지 않게 한다
            self.notices.append(msg)

    async def _complete(self, system: str, user: str, json_schema: dict) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            response_mime_type="application/json",
            response_json_schema=json_schema,
        )
        model = self.model_for(self.current_task)
        rate_waits = list(RATE_LIMIT_WAITS)
        server_waits = list(SERVER_WAITS)
        while True:
            try:
                resp = await self.client.aio.models.generate_content(
                    model=model, contents=user, config=config
                )
            except errors.ClientError as e:
                if e.code == 429:
                    daily, retry_sec = _daily_quota(e)
                    if daily:
                        self.exhausted.add(model)
                        if model != self.light_model and self.light_model not in self.exhausted:
                            self._notice(
                                f"{model} 오늘 무료 한도를 다 써서 {self.light_model}로 "
                                "대신 처리했다 (품질이 낮을 수 있다)"
                            )
                            model = self.light_model
                            continue
                        hours = (
                            f"약 {retry_sec / 3600:.0f}시간 뒤" if retry_sec else "태평양 시간 자정"
                        )
                        raise GeminiQuotaExhausted(
                            f"Gemini 무료 호출 한도를 오늘 다 썼다 ({model}) — {hours} 초기화된다. "
                            "기다리거나 LLM_MODE=ollama로 바꾼다"
                        ) from e
                    if rate_waits:  # 분당 한도는 잠시 기다리면 풀린다
                        await self._sleep(rate_waits.pop(0))
                        continue
                raise RuntimeError(f"Gemini 요청 실패 ({e.code}): {e.message}") from e
            except errors.ServerError as e:
                if server_waits:
                    await self._sleep(server_waits.pop(0))
                    continue
                if model != self.light_model and self.light_model not in self.exhausted:
                    # 주 모델 과부하가 계속되면 경량 모델로 넘기고, 한동안 주 모델을 건너뛴다
                    self._overloaded_until[model] = time.monotonic() + OVERLOAD_COOLDOWN_SEC
                    self._notice(
                        f"{model} 서버 과부하({e.code})가 계속돼 {self.light_model}로 "
                        "대신 처리했다 (품질이 낮을 수 있다)"
                    )
                    model = self.light_model
                    server_waits = list(SERVER_WAITS)
                    continue
                raise RuntimeError(f"Gemini 서버 오류 ({e.code}): {e.message}") from e
            text = resp.text
            if not text:
                reason = resp.candidates[0].finish_reason if resp.candidates else "응답 없음"
                raise RuntimeError(f"Gemini가 빈 응답을 돌려줬다 ({reason})")
            return text
