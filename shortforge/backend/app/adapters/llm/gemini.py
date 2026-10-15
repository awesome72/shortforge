"""Gemini 무료 등급 어댑터 (LLM_MODE=gemini, D3).

무료 등급 주의 (PRD §8): 분당·일일 호출 제한이 있고, 입력이 모델 개선에 쓰일 수 있으며,
상업적 이용에서 제외된다. 사업화 시점에는 Ollama로 전환한다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from google import genai
from google.genai import errors, types

from app.adapters.llm.common import JSONLLMAdapter

RATE_LIMIT_WAITS = (10, 25, 60)  # 429일 때 기다리는 초. 무료 등급은 분당 한도가 낮다
SERVER_RETRIES = 2


class GeminiAdapter(JSONLLMAdapter):
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
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
        self.temperature = temperature
        self._sleep = sleep
        self.client = client or genai.Client(api_key=api_key)

    async def _complete(self, system: str, user: str, json_schema: dict) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            response_mime_type="application/json",
            response_json_schema=json_schema,
        )
        rate_waits = list(RATE_LIMIT_WAITS)
        server_tries = SERVER_RETRIES
        while True:
            try:
                resp = await self.client.aio.models.generate_content(
                    model=self.model, contents=user, config=config
                )
            except errors.ClientError as e:
                if e.code == 429 and rate_waits:
                    await self._sleep(rate_waits.pop(0))
                    continue
                raise RuntimeError(f"Gemini 요청 실패 ({e.code}): {e.message}") from e
            except errors.ServerError as e:
                if server_tries:
                    server_tries -= 1
                    await self._sleep(3)
                    continue
                raise RuntimeError(f"Gemini 서버 오류 ({e.code}): {e.message}") from e
            text = resp.text
            if not text:
                reason = resp.candidates[0].finish_reason if resp.candidates else "응답 없음"
                raise RuntimeError(f"Gemini가 빈 응답을 돌려줬다 ({reason})")
            return text
