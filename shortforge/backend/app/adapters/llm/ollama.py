"""Ollama 로컬 LLM 어댑터 (LLM_MODE=ollama). 외부 호출 없이 동작한다 (제약 6, DoD).

RAM 8GB 개발 PC에서는 3B급 모델만 현실적이다. 한국어 품질은 Gemini보다 낮을 수 있다.
"""

from __future__ import annotations

import httpx

from app.adapters.llm.common import JSONLLMAdapter


class OllamaAdapter(JSONLLMAdapter):
    def __init__(
        self,
        host: str,
        model: str,
        *,
        temperature: float = 0.4,
        timeout: float = 300,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__()
        self.model = model
        self.temperature = temperature
        self.client = httpx.AsyncClient(base_url=host, timeout=timeout, transport=transport)

    async def _complete(self, system: str, user: str, json_schema: dict) -> str:
        try:
            resp = await self.client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "format": json_schema,  # 구조화 출력
                    "stream": False,
                    "options": {"temperature": self.temperature},
                },
            )
        except httpx.TransportError as e:
            raise RuntimeError(
                f"Ollama에 연결할 수 없다 ({self.client.base_url}) — "
                f"`ollama serve` 실행 여부 확인: {e}"
            ) from e
        if resp.status_code == 404:
            raise RuntimeError(f"Ollama 모델 '{self.model}'이 없다 — `ollama pull {self.model}`")
        resp.raise_for_status()
        return resp.json()["message"]["content"]
