"""Anthropic Claude 어댑터 (고급 모드, D13). 공식 `anthropic` SDK로 호출한다.

- 구조화 출력: `output_config.format`(json_schema)으로 스키마에 맞는 JSON만 받는다.
  API가 지원하지 않는 제약(글자 수·숫자 범위·배열 개수·pattern)은 보낼 스키마에서 빼고,
  받은 뒤 공통 처리(JSONLLMAdapter)가 Pydantic으로 다시 검증한다.
- 썸네일은 내려받지 않고 URL로 넘긴다 (`source.type: "url"`).
- 안전 분류기가 거절하면(`stop_reason: "refusal"`) 서버가 다른 모델로 다시 처리하도록
  `fallbacks: "default"`를 켠다(지원하는 모델만). 그래도 거절되면 예외를 내고,
  라우터가 무료 경로로 넘긴다.
- 토큰 사용량으로 비용을 계산해 SpendMeter에 남긴다. 프롬프트가 작업당 약 1천 토큰이라
  캐싱 최소 길이에 못 미쳐 프롬프트 캐싱은 쓰지 않는다.
"""

from __future__ import annotations

import time

import anthropic
from anthropic import AsyncAnthropic

from app.adapters.llm.common import JSONLLMAdapter
from app.metrics import record_llm_call
from app.spend import SpendMeter, cost_usd

PROVIDER = "anthropic"
MAX_TOKENS = 16000
REQUEST_TIMEOUT_SEC = 180.0
# 서버 측 거절 대체("default" 형식)를 받는 모델. Haiku 5.5는 서버 측 대체가 없다
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
UNSUPPORTED_KEYS = {
    "minLength", "maxLength", "pattern", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "multipleOf", "minItems", "maxItems", "uniqueItems",
}  # fmt: skip
SUPPORTED_FORMATS = {
    "date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid",
}  # fmt: skip


class AdvancedLLMError(RuntimeError):
    """고급 모드 요청 실패. 메시지에 키를 넣지 않는다."""


def strict_schema(node):
    """구조화 출력용 스키마: 모든 객체에 additionalProperties=false를 넣고 미지원 제약을 뺀다."""
    if isinstance(node, list):
        return [strict_schema(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in UNSUPPORTED_KEYS:
            continue
        if k == "format" and v not in SUPPORTED_FORMATS:
            continue
        out[k] = strict_schema(v) if k not in ("enum", "const", "required") else v
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
    return out


class AnthropicAdapter(JSONLLMAdapter):
    supports_images = True
    provider = PROVIDER

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        effort: str = "medium",
        spend: SpendMeter | None = None,
        http_client=None,
    ) -> None:
        super().__init__()
        if not api_key:
            raise RuntimeError(
                "고급 모드(Anthropic)가 켜져 있지만 ANTHROPIC_API_KEY가 비어 있다 — "
                "설정 화면의 '고급 모드'에서 키를 넣거나 고급 모드를 끈다"
            )
        self.model = model
        self.effort = effort
        self.spend = spend
        # 키를 명시적으로 넘긴다. 환경 변수나 다른 로그인 정보를 몰래 쓰지 않게 한다
        self.client = AsyncAnthropic(
            api_key=api_key,
            timeout=REQUEST_TIMEOUT_SEC,
            max_retries=2,
            http_client=http_client,
        )

    async def _complete(
        self, system: str, user: str, json_schema: dict, images: list[str] | None = None
    ) -> str:
        content: list[dict] = [
            {"type": "image", "source": {"type": "url", "url": u}} for u in images or []
        ]
        content.append({"type": "text", "text": user})
        kwargs: dict = {}
        if self.model in FALLBACK_MODELS:
            kwargs = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        task = self.current_task
        t0 = time.perf_counter()
        try:
            resp = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": strict_schema(json_schema)},
                },
                **kwargs,
            )
        except anthropic.APIStatusError as e:
            self._record(task, t0, ok=False, error=e.status_code)
            raise AdvancedLLMError(_describe(e)) from e
        except anthropic.APIConnectionError as e:
            self._record(task, t0, ok=False, error="connection")
            raise AdvancedLLMError("Anthropic에 연결하지 못했다 (인터넷 연결 확인)") from e

        served = resp.model or self.model
        usage = resp.usage
        tokens_in, tokens_out = usage.input_tokens or 0, usage.output_tokens or 0
        usd = (
            self.spend.record(PROVIDER, served, task, tokens_in, tokens_out)
            if self.spend
            else cost_usd(PROVIDER, served, tokens_in, tokens_out)
        )
        ok = resp.stop_reason not in ("refusal", "max_tokens")
        self._record(
            task, t0, ok=ok, model=served, in_tokens=tokens_in, out_tokens=tokens_out,
            usd=round(usd, 5), error=None if ok else resp.stop_reason,
        )  # fmt: skip
        if resp.stop_reason == "refusal":
            raise AdvancedLLMError("Claude가 이 요청을 거절했다 (안전 분류기)")
        if resp.stop_reason == "max_tokens":
            raise AdvancedLLMError("Claude 응답이 길이 한도에서 잘렸다")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        if not text:
            raise AdvancedLLMError("Claude가 빈 응답을 돌려줬다")
        return text

    def _record(self, task: str, t0: float, *, ok: bool, model: str | None = None, **fields):
        fields = {k: v for k, v in fields.items() if v is not None}
        record_llm_call(
            task=task, provider=PROVIDER, model=model or self.model,
            sec=round(time.perf_counter() - t0, 2), waited=0.0, ok=ok, **fields,
        )  # fmt: skip


def _describe(e: anthropic.APIStatusError) -> str:
    status = e.status_code
    if status == 401:
        return "Anthropic API 키가 맞지 않다 (401)"
    if status == 403:
        return "Anthropic API 키에 권한이 없다 (403)"
    if status == 404:
        return "Anthropic 모델을 찾을 수 없다 (404) — 설정의 모델 이름 확인"
    if status == 429:
        return "Anthropic 호출 한도에 걸렸다 (429)"
    if status == 402 or "credit" in str(e.message).lower() or "billing" in str(e.message).lower():
        return f"Anthropic 결제·크레딧 문제 ({status}) — 콘솔에서 크레딧을 확인한다"
    return f"Anthropic 요청 실패 ({status})"


async def check_key(api_key: str, http_client=None) -> tuple[bool | None, str]:
    """모델 목록 조회로 키를 확인한다(토큰을 쓰지 않아 비용 없음)."""
    client = AsyncAnthropic(api_key=api_key, timeout=30.0, max_retries=0, http_client=http_client)
    try:
        page = await client.models.list(limit=20)
    except anthropic.AuthenticationError:
        return False, "키가 맞지 않다 — console.anthropic.com의 API Keys에서 다시 복사한다"
    except anthropic.PermissionDeniedError:
        return False, "이 키에는 API 권한이 없다"
    except anthropic.APIConnectionError:
        return None, "응답 없음 — 인터넷 연결을 확인한다"
    except anthropic.APIStatusError as e:
        return False, f"키 확인 실패 (HTTP {e.status_code})"
    ids = [m.id for m in page.data]
    return True, f"키 유효 (모델 {len(ids)}개 확인, 확인 비용 없음)"
