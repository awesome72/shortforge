"""LLM 어댑터 공통 재시도, Gemini/Ollama 어댑터 (실제 호출 없음)."""

import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from app.adapters.llm.common import JSONLLMAdapter, LLMOutputError, llm_schema, strip_fences
from app.adapters.llm.gemini import GeminiAdapter
from app.adapters.llm.ollama import OllamaAdapter
from app.schemas.project import Strategy
from app.steps.s1_input import KeywordsOut

GOOD = json.dumps({"keywords": ["가", "나", "다"]})


class Scripted(JSONLLMAdapter):
    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)
        self.prompts = []

    async def _complete(self, system, user, json_schema):
        self.prompts.append(user)
        return self.replies.pop(0)


def test_llm_schema_inlines_refs_and_drops_titles():
    schema = llm_schema(Strategy)

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k != "properties":  # properties 아래 키는 필드 이름이다
                    yield k
                yield from keys(v)
        elif isinstance(node, list):
            for x in node:
                yield from keys(x)

    found = set(keys(schema))
    assert not found & {"$ref", "$defs", "title", "default"}
    scene = schema["properties"]["scenes"]["items"]
    assert scene["properties"]["role"]["enum"] == ["hook", "problem", "method", "payoff", "cta"]
    assert schema["properties"]["scenes"]["minItems"] == 5


def test_strip_fences():
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('  {"a": 1} ') == '{"a": 1}'


async def test_retry_with_validation_feedback():
    llm = Scripted(['{"keywords": ["하나"]}', GOOD])
    out = await llm.generate_json("s1_keywords", "sys", "원래 요청", KeywordsOut)
    assert out.keywords == ["가", "나", "다"]
    assert "스키마 검증에 실패" in llm.prompts[1] and "keywords" in llm.prompts[1]
    assert llm.prompts[1].startswith("원래 요청")
    assert llm.log.calls[-1].attempts == 2 and llm.log.calls[-1].ok


async def test_gives_up_after_three_attempts():
    llm = Scripted(["not json"] * 3)
    with pytest.raises(LLMOutputError, match="3회"):
        await llm.generate_json("s1_keywords", "sys", "u", KeywordsOut)
    assert len(llm.prompts) == 3 and llm.log.calls[-1].ok is False


# ── Gemini ────────────────────────────────────────────────


class FakeGenAI:
    """genai.Client 모양만 흉내 낸다: client.aio.models.generate_content."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.configs = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._gen))

    async def _gen(self, model, contents, config):
        self.configs.append((model, config))
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return SimpleNamespace(text=o, candidates=[])


def _client_error(code, msg):
    return errors.ClientError(code, {"error": {"code": code, "message": msg}})


async def test_gemini_sends_schema_and_retries_rate_limit():
    waits = []

    async def sleep(s):
        waits.append(s)

    fake = FakeGenAI([_client_error(429, "rate"), _client_error(429, "rate"), GOOD])
    g = GeminiAdapter("", "gemini-3.8-flash", client=fake, sleep=sleep)
    out = await g.generate_json("s1_keywords", "시스템", "u", KeywordsOut)
    assert out.keywords == ["가", "나", "다"]
    assert waits == [10, 25]
    model, config = fake.configs[-1]
    assert model == "gemini-3.8-flash"
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["properties"]["keywords"]["minItems"] == 3
    assert config.system_instruction == "시스템"


async def test_gemini_billing_error_is_not_retried():
    fake = FakeGenAI([_client_error(402, "Your prepayment credits are depleted")])
    g = GeminiAdapter("", "m", client=fake)
    with pytest.raises(RuntimeError, match="402"):
        await g.generate_json("s1_keywords", "s", "u", KeywordsOut)
    assert len(fake.configs) == 1


def test_gemini_requires_key():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiAdapter("", "m")


# ── Ollama ────────────────────────────────────────────────


async def test_ollama_structured_output_request():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": f"```json\n{GOOD}\n```"}})

    o = OllamaAdapter("http://ollama", "qwen2.5:3b", transport=httpx.MockTransport(handler))
    out = await o.generate_json("s1_keywords", "시스템", "사용자", KeywordsOut)
    assert out.keywords == ["가", "나", "다"]
    assert seen["model"] == "qwen2.5:3b" and seen["stream"] is False
    assert seen["format"]["properties"]["keywords"]["type"] == "array"
    assert [m["role"] for m in seen["messages"]] == ["system", "user"]


async def test_ollama_errors_are_actionable():
    def offline(request):
        raise httpx.ConnectError("refused")

    o = OllamaAdapter("http://ollama", "m", transport=httpx.MockTransport(offline))
    with pytest.raises(RuntimeError, match="ollama serve"):
        await o.generate_json("t", "s", "u", KeywordsOut)

    missing = OllamaAdapter(
        "http://ollama", "qwen", transport=httpx.MockTransport(lambda r: httpx.Response(404))
    )
    with pytest.raises(RuntimeError, match="ollama pull qwen"):
        await missing.generate_json("t", "s", "u", KeywordsOut)
