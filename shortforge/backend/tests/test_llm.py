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


# ── 무료 등급 일일 한도 (2026-10 실측: 3.8-flash 하루 20회) ─────────


DAILY_QUOTA_ID = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"


def _daily_429(retry="67718s"):
    return errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "You exceeded your current quota",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                     "violations": [{"quotaId": DAILY_QUOTA_ID}]},
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry},
                ],
            }
        },
    )  # fmt: skip


class ModelAwareGenAI(FakeGenAI):
    """모델별로 일일 한도 소진을 흉내 낸다."""

    def __init__(self, exhausted=()):
        super().__init__([])
        self.exhausted = set(exhausted)
        self.models = []

    async def _gen(self, model, contents, config):
        self.models.append(model)
        if model in self.exhausted:
            raise _daily_429()
        return SimpleNamespace(text=GOOD, candidates=[])


async def test_tasks_routed_to_light_or_main_model():
    fake = ModelAwareGenAI()
    g = GeminiAdapter("", "main", light_model="lite", client=fake)
    tasks = ("s1_keywords", "s2_relevance", "s3_factors", "s4_strategy", "s5_image_prompts",
             "s6_timeline")  # fmt: skip
    for task in tasks:
        await g.generate_json(task, "s", "u", KeywordsOut)
    assert fake.models == ["lite", "lite", "main", "main", "lite", "lite"]


async def test_daily_quota_falls_back_to_light_without_waiting():
    waits = []

    async def sleep(s):
        waits.append(s)

    fake = ModelAwareGenAI(exhausted={"main"})
    g = GeminiAdapter("", "main", light_model="lite", client=fake, sleep=sleep)
    await g.generate_json("s3_factors", "s", "u", KeywordsOut)
    await g.generate_json("s4_strategy", "s", "u", KeywordsOut)
    assert fake.models == ["main", "lite", "lite"]  # 두 번째부터는 바로 경량 모델
    assert waits == []  # 일일 한도는 기다려도 풀리지 않는다
    notes = g.drain_notices()
    assert len(notes) == 1 and "main 오늘 무료 한도" in notes[0]
    assert g.drain_notices() == []


async def test_all_models_exhausted_fails_fast_with_reset_time():
    from app.adapters.llm.gemini import GeminiQuotaExhausted

    fake = ModelAwareGenAI(exhausted={"main", "lite"})
    g = GeminiAdapter("", "main", light_model="lite", client=fake)
    with pytest.raises(GeminiQuotaExhausted, match="약 19시간 뒤"):
        await g.generate_json("s4_strategy", "s", "u", KeywordsOut)


async def test_fallback_notice_reaches_step_warnings(orch, store, adapters, sample_input):
    p = await orch.run_all(store.create(sample_input).id)
    adapters.llm.notices = ["main 오늘 무료 한도를 다 써서 lite로 대신 처리했다"]
    p = await orch.run_step(p.id, "s4")
    assert "main 오늘 무료 한도를 다 써서 lite로 대신 처리했다" in p.warnings["s4"]


async def test_server_overload_waits_then_falls_back_to_light():
    """실측: 3.8-flash 503 high demand가 3초×2회 재시도로 풀리지 않아 S4가 실패했다."""
    waits = []

    async def sleep(sec):
        waits.append(sec)

    class Overloaded(ModelAwareGenAI):
        async def _gen(self, model, contents, config):
            self.models.append(model)
            if model == "main":
                raise errors.ServerError(503, {"error": {"code": 503, "message": "high demand"}})
            return SimpleNamespace(text=GOOD, candidates=[])

    fake = Overloaded()
    g = GeminiAdapter("", "main", light_model="lite", client=fake, sleep=sleep)
    await g.generate_json("s4_strategy", "s", "u", KeywordsOut)
    assert waits == [5, 15, 30]
    assert fake.models == ["main"] * 4 + ["lite"]
    # 과부하가 확인된 주 모델은 한동안 건너뛴다 (매 호출 50초씩 기다리지 않는다)
    await g.generate_json("s4_strategy", "s", "u", KeywordsOut)
    assert fake.models[-1] == "lite" and waits == [5, 15, 30]
    notes = g.drain_notices()
    assert len(notes) == 1 and "서버 과부하(503)" in notes[0]  # 같은 알림은 한 번만
