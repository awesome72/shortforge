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
from app.metrics import record_llm_call

RATE_LIMIT_WAITS = (10, 25, 60)  # 분당 한도(429)일 때 기다리는 초
# 503(과부하) 등 서버 오류일 때 기다리는 초.
# 경량 모델로 넘길 수 있으면 짧게 한 번만 기다리고 넘긴다. 2026-10 실측에서 과부하는 3초×2회로
# 풀리지 않았고, 5·15·30초를 다 기다린 뒤 결국 경량 모델로 넘어가 호출 하나가 50초 넘게 걸렸다.
SERVER_WAITS_BEFORE_FALLBACK = (3,)
# 넘길 모델이 없으면(이미 경량 모델이거나 경량 모델도 한도 소진) 길게 기다린다
SERVER_WAITS = (5, 15, 30)
LIGHT_TASKS = frozenset(
    {
        "s1_keywords",
        "s2_relevance",
        # D18: 공식 카드 품질이 비슷한데 주 모델은 중앙값 131초(경량 6초)다. 대사만 주 모델
        "s3_factors",
        "s3_thumbnails",
        "s4_concepts",
        "s4_shorten",
        "s4_lengthen",
        "s5_image_prompts",
        "s5_video_check",
        "s6_timeline",
    }
)
# 실패해도 단계가 그대로 이어지는 보조 작업. 과부하면 3초 한 번만 기다리고 건너뛴다
# (2026-10 실측: s3_thumbnails가 503에 5·15·30초를 다 기다려 S3 76.9초 중 약 62초를 결과 없이 썼다)
OPTIONAL_TASKS = frozenset({"s2_relevance", "s3_thumbnails", "s4_concepts", "s5_video_check"})
OVERLOAD_COOLDOWN_SEC = 600  # 과부하가 확인된 모델은 이 시간 동안 건너뛴다


class GeminiQuotaExhausted(RuntimeError):
    """오늘 무료 호출 한도를 다 썼다 (기다려도 풀리지 않는다)."""


def _daily_quota(e: errors.ClientError) -> tuple[bool, float | None]:
    """(일일 한도 초과인가, 초기화까지 남은 초)."""
    raw = json.dumps(e.details or {}, ensure_ascii=False)
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', raw)
    return "PerDay" in raw, float(m.group(1)) if m else None


class GeminiAdapter(JSONLLMAdapter):
    supports_images = True  # 공개 HTTPS 이미지 URL을 Gemini가 직접 읽는다 (내려받지 않는다)

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        light_model: str | None = None,
        light_tasks: frozenset[str] = LIGHT_TASKS,
        temperature: float = 0.4,
        thinking_level: str = "",
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        client: genai.Client | None = None,
    ) -> None:
        super().__init__()
        if not api_key and client is None:
            raise RuntimeError(
                "GEMINI_API_KEY가 비어 있다 — "
                "설정 화면(또는 shortforge/.env)에 넣거나 LLM_MODE=ollama"
            )
        self.model = model
        self.light_model = light_model or model
        self.light_tasks = light_tasks
        self.temperature = temperature
        # 주 모델의 사고 수준 (minimal|low|medium|high, ""=모델 기본값).
        # 경량 모델은 사고하지 않으므로 넣지 않는다 (지원하지 않는 값이면 거절될 수 있다).
        # 2026-10 측정: 3.8-flash 기본값은 대본 요청에 사고 토큰 1,299개·27.6초, low는 20.6초
        self.thinking_level = thinking_level.strip().upper()
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

    def _can_fall_back(self, model: str) -> bool:
        return model != self.light_model and self.light_model not in self.exhausted

    def _server_waits(self, model: str) -> list[float]:
        if self._can_fall_back(model) or self.current_task in OPTIONAL_TASKS:
            return list(SERVER_WAITS_BEFORE_FALLBACK)
        return list(SERVER_WAITS)

    async def _complete(
        self, system: str, user: str, json_schema: dict, images: list[str] | None = None
    ) -> str:
        def config_for(model: str) -> types.GenerateContentConfig:
            thinking = None
            if self.thinking_level and model != self.light_model:
                thinking = types.ThinkingConfig(thinking_level=self.thinking_level)
            return types.GenerateContentConfig(
                system_instruction=system,
                temperature=self.temperature,
                response_mime_type="application/json",
                response_json_schema=json_schema,
                thinking_config=thinking,
            )

        contents: str | list = user
        if images:
            contents = [
                *(types.Part.from_uri(file_uri=u, mime_type="image/jpeg") for u in images),
                user,
            ]
        model = self.model_for(self.current_task)
        # 앞 단계의 과부하·한도로 이번 단계도 경량 모델로 넘어갔으면 이 단계에서도 알린다
        if (
            self.current_task not in self.light_tasks
            and model != self.model
            and not any(self.model in n for n in self.notices)
        ):
            self._notice(
                f"{self.model}를 지금 쓸 수 없어 {model}로 대신 처리했다 (품질이 낮을 수 있다)"
            )
        rate_waits = list(RATE_LIMIT_WAITS)
        server_waits = self._server_waits(model)
        waited = 0.0

        async def wait(sec: float) -> None:
            nonlocal waited
            waited += sec
            await self._sleep(sec)

        def record(t0: float, **fields) -> None:
            # 속도 분석용 (metrics.jsonl의 llm_call). 주제·대사는 넣지 않는다
            record_llm_call(
                task=self.current_task, provider="gemini", model=model,
                sec=round(time.perf_counter() - t0, 2), waited=round(waited, 1), **fields,
            )  # fmt: skip

        while True:
            t0 = time.perf_counter()
            try:
                resp = await self.client.aio.models.generate_content(
                    model=model, contents=contents, config=config_for(model)
                )
            except errors.ClientError as e:
                record(t0, ok=False, error=e.code)
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
                        await wait(rate_waits.pop(0))
                        continue
                raise RuntimeError(f"Gemini 요청 실패 ({e.code}): {e.message}") from e
            except errors.ServerError as e:
                record(t0, ok=False, error=e.code)
                if server_waits:
                    await wait(server_waits.pop(0))
                    continue
                if self._can_fall_back(model):
                    # 주 모델 과부하가 계속되면 경량 모델로 넘기고, 한동안 주 모델을 건너뛴다
                    self._overloaded_until[model] = time.monotonic() + OVERLOAD_COOLDOWN_SEC
                    self._notice(
                        f"{model} 서버 과부하({e.code})가 계속돼 {self.light_model}로 "
                        "대신 처리했다 (품질이 낮을 수 있다)"
                    )
                    model = self.light_model
                    server_waits = self._server_waits(model)
                    continue
                raise RuntimeError(f"Gemini 서버 오류 ({e.code}): {e.message}") from e
            usage = getattr(resp, "usage_metadata", None)
            record(
                t0, ok=True,
                thoughts=getattr(usage, "thoughts_token_count", None),
                out_tokens=getattr(usage, "candidates_token_count", None),
            )  # fmt: skip
            text = resp.text
            if not text:
                reason = resp.candidates[0].finish_reason if resp.candidates else "응답 없음"
                raise RuntimeError(f"Gemini가 빈 응답을 돌려줬다 ({reason})")
            return text
