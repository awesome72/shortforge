"""OpenAI·OpenRouter 어댑터 (고급 모드, D13).

둘 다 OpenAI 호환 Chat Completions 형식이라 어댑터 하나로 쓴다.

- 이미 의존성에 있는 httpx로 호출한다 (새 SDK를 늘리지 않는다).
- 구조화 출력: `response_format: json_schema`. 우리 스키마에는 기본값이 있는 선택 필드가 있어
  OpenAI strict 모드(모든 필드 required)에 맞지 않으므로 strict=false로 보내고,
  받은 뒤 공통 처리(JSONLLMAdapter)가 Pydantic으로 검증·재시도한다.
- OpenRouter는 모델마다 여러 제공 서버가 있고 구조화 출력 지원이 서버마다 다르다.
  `provider.require_parameters=true`로 그 기능을 지원하는 서버로만 보낸다.
- 비용: OpenRouter가 응답에 실제 청구액(usage.cost)을 주면 그것을, 아니면 토큰 × 가격표로 계산한다.
"""

from __future__ import annotations

import time

import httpx

from app.adapters.llm.advanced.anthropic_api import AdvancedLLMError, strict_schema
from app.adapters.llm.common import JSONLLMAdapter
from app.metrics import record_llm_call
from app.spend import SpendMeter, cost_usd

BASE_URL = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
LABEL = {"openai": "OpenAI", "openrouter": "OpenRouter"}
MAX_COMPLETION_TOKENS = 16000
REQUEST_TIMEOUT_SEC = 180.0


class OpenAICompatAdapter(JSONLLMAdapter):
    supports_images = True

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        *,
        effort: str = "medium",
        spend: SpendMeter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__()
        if provider not in BASE_URL:
            raise ValueError(provider)
        env = f"{provider.upper()}_API_KEY"
        if not api_key:
            raise RuntimeError(
                f"고급 모드({LABEL[provider]})가 켜져 있지만 {env}가 비어 있다 — "
                "설정 화면의 '고급 모드'에서 키를 넣거나 고급 모드를 끈다"
            )
        self.provider = provider
        self.model = model
        self.effort = effort
        self.spend = spend
        headers = {"Authorization": f"Bearer {api_key}"}
        if provider == "openrouter":  # OpenRouter 앱 식별용(선택)
            headers |= {"X-Title": "ShortForge"}
        self.client = httpx.AsyncClient(
            base_url=BASE_URL[provider],
            headers=headers,
            timeout=REQUEST_TIMEOUT_SEC,
            transport=transport,
        )

    def _body(self, system: str, user: str, json_schema: dict, images: list[str] | None) -> dict:
        content: list[dict] = [{"type": "text", "text": user}]
        content += [{"type": "image_url", "image_url": {"url": u}} for u in images or []]
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "output",
                    "strict": False,
                    "schema": strict_schema(json_schema),
                },  # fmt: skip
            },
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
        }
        if self.provider == "openai":
            body["reasoning_effort"] = self.effort
        else:
            body["reasoning"] = {"effort": self.effort}
            body["provider"] = {"require_parameters": True}
            body["usage"] = {"include": True}
        return body

    async def _complete(
        self, system: str, user: str, json_schema: dict, images: list[str] | None = None
    ) -> str:
        task = self.current_task
        t0 = time.perf_counter()
        try:
            r = await self.client.post(
                "/chat/completions", json=self._body(system, user, json_schema, images)
            )
        except httpx.HTTPError as e:
            self._record(task, t0, ok=False, error="connection")
            raise AdvancedLLMError(f"{LABEL[self.provider]}에 연결하지 못했다") from e
        data = _json(r)
        if r.status_code != 200 or "error" in data:
            self._record(task, t0, ok=False, error=r.status_code)
            raise AdvancedLLMError(_describe(self.provider, r.status_code, data))

        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
        served = data.get("model") or self.model
        reported = usage.get("cost")  # OpenRouter 실제 청구액(USD)
        usd = (
            float(reported)
            if isinstance(reported, int | float)
            else cost_usd(self.provider, self.model, tokens_in, tokens_out)
        )
        if self.spend:
            self.spend.record_usd(self.provider, served, task, tokens_in, tokens_out, usd)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        finish = choice.get("finish_reason")
        refused = bool(message.get("refusal"))
        ok = not refused and finish != "length"
        self._record(
            task, t0, ok=ok, model=served, in_tokens=tokens_in, out_tokens=tokens_out,
            usd=round(usd, 5), error=None if ok else ("refusal" if refused else finish),
        )  # fmt: skip
        if refused:
            raise AdvancedLLMError(f"{LABEL[self.provider]} 모델이 이 요청을 거절했다")
        if finish == "length":
            raise AdvancedLLMError(f"{LABEL[self.provider]} 응답이 길이 한도에서 잘렸다")
        text = message.get("content") or ""
        if isinstance(text, list):  # 일부 서버는 내용 블록 목록으로 준다
            text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
        if not text:
            raise AdvancedLLMError(f"{LABEL[self.provider]}가 빈 응답을 돌려줬다")
        return text

    def _record(self, task: str, t0: float, *, ok: bool, model: str | None = None, **fields):
        fields = {k: v for k, v in fields.items() if v is not None}
        record_llm_call(
            task=task, provider=self.provider, model=model or self.model,
            sec=round(time.perf_counter() - t0, 2), waited=0.0, ok=ok, **fields,
        )  # fmt: skip


def _json(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _describe(provider: str, status: int, data: dict) -> str:
    name = LABEL[provider]
    if status == 401:
        return f"{name} API 키가 맞지 않다 (401)"
    if status == 402:
        return f"{name} 크레딧이 부족하다 (402) — 계정에서 잔액을 확인한다"
    if status == 403:
        return f"{name} 키에 이 모델 권한이 없다 (403)"
    if status == 404:
        return f"{name}에서 모델을 찾을 수 없다 (404) — 설정의 모델 이름 확인"
    if status == 429:
        return f"{name} 호출 한도에 걸렸다 (429)"
    err = data.get("error") if isinstance(data.get("error"), dict) else {}
    msg = str(err.get("message", ""))[:120]
    return f"{name} 요청 실패 ({status}){': ' + msg if msg else ''}"


async def check_key(
    provider: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[bool | None, str]:
    """토큰을 쓰지 않는 조회로 키를 확인한다. OpenAI는 모델 목록, OpenRouter는 키 정보."""
    path = "/models" if provider == "openai" else "/key"
    async with httpx.AsyncClient(
        base_url=BASE_URL[provider],
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
        transport=transport,
    ) as c:
        try:
            r = await c.get(path)
        except httpx.HTTPError:
            return None, "응답 없음 — 인터넷 연결을 확인한다"
    if r.status_code in (401, 403):
        return False, "키가 맞지 않다 — 계정의 API 키 화면에서 다시 복사한다"
    if r.status_code != 200:
        return False, f"키 확인 실패 (HTTP {r.status_code})"
    if provider == "openrouter":
        info = (_json(r).get("data") or {}) if r.status_code == 200 else {}
        limit = info.get("limit_remaining")
        left = f", 남은 한도 ${limit:.2f}" if isinstance(limit, int | float) else ""
        return True, f"키 유효 (확인 비용 없음{left})"
    return True, "키 유효 (모델 목록 확인, 확인 비용 없음)"
