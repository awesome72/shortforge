"""고급 모드(D13): OpenAI·OpenRouter (OpenAI 호환 어댑터 하나). 실제 API는 가짜 서버로 대체한다."""

import json

import httpx
import pytest

from app.adapters.llm.advanced.anthropic_api import AdvancedLLMError
from app.adapters.llm.advanced.openai_compat import OpenAICompatAdapter, check_key
from app.adapters.llm.routed import RoutedLLM
from app.metrics import LLM_CALLS
from app.spend import SpendMeter
from app.steps.s1_input import KeywordsOut

GOOD = '{"keywords": ["a", "b", "c"]}'


def server(seen, *, content=GOOD, status=200, usage=None, finish="stop", refusal=None):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        seen.append((request, body))
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "nope"}})
        return httpx.Response(
            200,
            json={
                "id": "c1", "model": body.get("model"),
                "choices": [{
                    "index": 0, "finish_reason": finish,
                    "message": {"role": "assistant", "content": content, "refusal": refusal},
                }],
                "usage": usage or {"prompt_tokens": 1000, "completion_tokens": 500},
            },
        )  # fmt: skip

    return httpx.MockTransport(handler)


@pytest.fixture
def spend(tmp_path):
    return SpendMeter(tmp_path / "db.sqlite", daily_budget_usd=1.0)


async def test_openai_request_shape_and_cost(spend):
    seen = []
    a = OpenAICompatAdapter(
        "openai", "sk-oa-test", "gpt-5.6-sol", effort="low", spend=spend, transport=server(seen)
    )
    token = LLM_CALLS.set([])
    try:
        out = await a.generate_json(
            "s3_factors", "sys", "user", KeywordsOut, images=["https://i.ytimg.com/vi/x/hq.jpg"]
        )
        calls = LLM_CALLS.get()
    finally:
        LLM_CALLS.reset(token)
    assert out.keywords == ["a", "b", "c"]
    request, body = seen[0]
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-oa-test"
    assert body["model"] == "gpt-5.6-sol" and body["reasoning_effort"] == "low"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    text, image = body["messages"][1]["content"]
    assert text == {"type": "text", "text": "user"}
    assert image == {"type": "image_url", "image_url": {"url": "https://i.ytimg.com/vi/x/hq.jpg"}}
    rf = body["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is False
    assert rf["json_schema"]["schema"]["additionalProperties"] is False
    assert "provider" not in body and "reasoning" not in body
    # 1000 × $4/M + 500 × $20/M = $0.014
    assert spend.used() == pytest.approx(0.014)
    assert calls[0]["provider"] == "openai" and calls[0]["usd"] == pytest.approx(0.014)


async def test_openrouter_uses_reported_cost_and_requires_parameters(spend):
    seen = []
    usage = {"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.0123}
    a = OpenAICompatAdapter(
        "openrouter", "sk-or-test", "anthropic/claude-sonnet-5.5", spend=spend,
        transport=server(seen, usage=usage),
    )  # fmt: skip
    await a.generate_json("s4_strategy", "sys", "user", KeywordsOut)
    request, body = seen[0]
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    # 구조화 출력을 지원하는 제공 서버로만 보낸다
    assert body["provider"] == {"require_parameters": True}
    assert body["reasoning"] == {"effort": "medium"} and body["usage"] == {"include": True}
    assert "reasoning_effort" not in body
    assert spend.used() == pytest.approx(0.0123)  # 토큰 계산이 아니라 실제 청구액


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"refusal": "I can't help"}, "거절"),
        ({"finish": "length"}, "잘렸다"),
        ({"status": 401}, "키가 맞지 않다"),
        ({"status": 402}, "크레딧"),
    ],
)
async def test_failures_raise(spend, kwargs, match):
    a = OpenAICompatAdapter(
        "openai", "sk-oa-test", "gpt-5.6-sol", spend=spend, transport=server([], **kwargs)
    )
    with pytest.raises(AdvancedLLMError, match=match):
        await a.generate_json("s4_strategy", "sys", "user", KeywordsOut)


async def test_check_key_is_free_lookup():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers["authorization"] != "Bearer good-key-1234":
            return httpx.Response(401, json={"error": {"message": "bad"}})
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit_remaining": 4.5}})
        return httpx.Response(200, json={"data": []})

    t = httpx.MockTransport(handler)
    assert (await check_key("openai", "good-key-1234", t))[0] is True
    assert seen[-1].url.path == "/v1/models"
    ok, msg = await check_key("openrouter", "good-key-1234", t)
    assert ok is True and "$4.50" in msg and seen[-1].url.path == "/api/v1/key"
    assert (await check_key("openai", "bad-key-12345", t))[0] is False


def test_missing_key_is_setup_problem():
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenAICompatAdapter("openrouter", "", "anthropic/claude-opus-5.5")


@pytest.mark.parametrize(
    ("provider", "key_field", "model"),
    [("openai", "openai_api_key", "gpt-5.6-sol"),
     ("openrouter", "openrouter_api_key", "anthropic/claude-sonnet-5.5")],
)  # fmt: skip
def test_registry_builds_openai_compat(tmp_path, provider, key_field, model):
    from app.adapters.registry import build_adapters
    from app.config import Settings

    s = Settings(
        _env_file=None, data_dir=tmp_path, gemini_api_key="g", llm_advanced=provider,
        **{key_field: "k-123456"},
    )  # fmt: skip
    llm = build_adapters(s, problems=[]).llm
    assert isinstance(llm, RoutedLLM) and isinstance(llm.advanced, OpenAICompatAdapter)
    assert llm.advanced.provider == provider and llm.advanced.model == model
