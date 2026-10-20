"""고급 모드(D13): Anthropic 어댑터·작업별 라우팅·하루 예산. 실제 API는 가짜 서버로 대체한다."""

import json

import httpx2
import pytest
from pydantic import BaseModel

from app.adapters.fake import FakeLLM
from app.adapters.llm.advanced.anthropic_api import AnthropicAdapter, strict_schema
from app.adapters.llm.common import llm_schema
from app.adapters.llm.routed import RoutedLLM
from app.metrics import LLM_CALLS
from app.schemas.project import Strategy
from app.spend import SpendMeter
from app.steps.s1_input import KeywordsOut


class Out(BaseModel):
    keywords: list[str]


def anthropic_server(requests, *, stop_reason="end_turn", status=200, text=None):
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content) if request.content else {}
        requests.append((request, body))
        if status != 200:
            return httpx2.Response(status, json={"type": "error", "error": {"message": "x"}})
        return httpx2.Response(
            200,
            json={
                "id": "msg_1", "type": "message", "role": "assistant",
                "model": body.get("model"), "stop_reason": stop_reason, "stop_sequence": None,
                "content": [{"type": "text", "text": text or '{"keywords": ["a", "b"]}'}],
                "usage": {"input_tokens": 1000, "output_tokens": 500},
            },
        )  # fmt: skip

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


@pytest.fixture
def spend(tmp_path):
    return SpendMeter(tmp_path / "db.sqlite", daily_budget_usd=1.0)


def test_strict_schema_closes_objects_and_drops_unsupported():
    s = strict_schema(llm_schema(Strategy))
    assert s["additionalProperties"] is False
    scene = s["properties"]["scenes"]["items"]
    assert scene["additionalProperties"] is False
    dumped = json.dumps(s)
    for key in ("minItems", "maxItems", "pattern", "minimum"):
        assert f'"{key}"' not in dumped


async def test_request_shape_and_cost(spend):
    reqs = []
    a = AnthropicAdapter(
        "sk-test", "claude-opus-5-5", effort="low", spend=spend, http_client=anthropic_server(reqs)
    )
    token = LLM_CALLS.set([])
    try:
        out = await a.generate_json(
            "s3_factors", "sys", "user", Out, images=["https://i.ytimg.com/vi/x/hq.jpg"]
        )
        calls = LLM_CALLS.get()
    finally:
        LLM_CALLS.reset(token)
    assert out.keywords == ["a", "b"]
    request, body = reqs[0]
    assert body["model"] == "claude-opus-5-5" and body["system"] == "sys"
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    image, text = body["messages"][0]["content"]
    assert image["source"] == {"type": "url", "url": "https://i.ytimg.com/vi/x/hq.jpg"}
    assert text == {"type": "text", "text": "user"}
    # 거절되면 서버가 다른 모델로 다시 처리한다 (지원 모델)
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]
    assert request.headers["x-api-key"] == "sk-test"
    # 1000 입력 × $4/M + 500 출력 × $20/M = $0.014
    assert spend.used() == pytest.approx(0.014)
    assert calls[0]["provider"] == "anthropic" and calls[0]["usd"] == pytest.approx(0.014)
    assert calls[0]["in_tokens"] == 1000 and calls[0]["task"] == "s3_factors"


async def test_haiku_sends_no_fallbacks(spend):
    reqs = []
    a = AnthropicAdapter(
        "sk-test", "claude-haiku-5-5", spend=spend, http_client=anthropic_server(reqs)
    )
    await a.generate_json("s4_strategy", "sys", "user", Out)
    request, body = reqs[0]
    assert "fallbacks" not in body
    assert "server-side-fallback" not in request.headers.get("anthropic-beta", "")


async def test_refusal_raises(spend):
    from app.adapters.llm.advanced.anthropic_api import AdvancedLLMError

    reqs = []
    a = AnthropicAdapter(
        "sk-test", "claude-opus-5-5", spend=spend,
        http_client=anthropic_server(reqs, stop_reason="refusal", text="{}"),
    )  # fmt: skip
    with pytest.raises(AdvancedLLMError, match="거절"):
        await a.generate_json("s4_strategy", "sys", "user", Out)
    assert spend.used() > 0  # 거절도 비용이 기록된다


def test_missing_key_is_setup_problem():
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicAdapter("", "claude-opus-5-5")


# ── 라우팅 ──────────────────────────────────────────────


class Recorder(FakeLLM):
    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail

    async def generate_json(self, task, system, user, schema, *, images=()):
        if self.fail:
            raise RuntimeError("Anthropic API 키가 맞지 않다 (401)")
        return await super().generate_json(task, system, user, schema, images=images)


async def test_router_sends_only_chosen_tasks(spend):
    base, adv = Recorder(), Recorder()
    r = RoutedLLM(base, adv, {"s3_factors", "s4_strategy"}, spend, label="Claude")
    await r.generate_json("s1_keywords", "s", "u", KeywordsOut)
    await r.generate_json("s4_strategy", "s", "u", Strategy)
    assert base.calls == ["s1_keywords"] and adv.calls == ["s4_strategy"]
    assert r.drain_notices() == []


async def test_router_falls_back_on_failure_with_notice(spend):
    base, adv = Recorder(), Recorder(fail=True)
    r = RoutedLLM(base, adv, {"s4_strategy"}, spend, label="Claude Opus 5.5")
    out = await r.generate_json("s4_strategy", "s", "u", Strategy)
    assert out.scenes and base.calls == ["s4_strategy"]
    notes = r.drain_notices()
    assert len(notes) == 1 and "고급 모드(Claude Opus 5.5)가 실패" in notes[0] and "401" in notes[0]


async def test_router_stops_paid_calls_over_budget(tmp_path):
    spend = SpendMeter(tmp_path / "db.sqlite", daily_budget_usd=0.01)
    spend.record("anthropic", "claude-opus-5-5", "s4_strategy", 1000, 500)  # $0.014
    base, adv = Recorder(), Recorder()
    r = RoutedLLM(base, adv, {"s4_strategy"}, spend, label="Claude")
    await r.generate_json("s4_strategy", "s", "u", Strategy)
    assert adv.calls == [] and base.calls == ["s4_strategy"]
    assert any("예산" in n for n in r.drain_notices())


# ── 조립 ────────────────────────────────────────────────


def test_registry_builds_router_only_when_enabled(tmp_path):
    from app.adapters.registry import build_adapters
    from app.config import Settings

    common = dict(_env_file=None, data_dir=tmp_path, gemini_api_key="g-key")
    off = build_adapters(Settings(**common), problems=[])
    assert not isinstance(off.llm, RoutedLLM)

    on = build_adapters(
        Settings(**common, llm_advanced="anthropic", anthropic_api_key="sk-test"), problems=[]
    )
    assert isinstance(on.llm, RoutedLLM)
    assert on.llm.advanced.model == "claude-sonnet-5-5"  # 실측으로 정한 기본 (D13)
    assert on.llm.tasks == {"s3_factors", "s4_strategy"}

    problems = []
    no_key = build_adapters(Settings(**common, llm_advanced="anthropic"), problems=problems)
    assert not isinstance(no_key.llm, RoutedLLM)  # 무료 경로는 그대로 쓴다
    assert any("ANTHROPIC_API_KEY" in p for p in problems)


def test_unknown_model_is_refused(tmp_path):
    from app.adapters.registry import build_adapters
    from app.config import Settings

    problems = []
    s = Settings(
        _env_file=None, data_dir=tmp_path, gemini_api_key="g", llm_advanced="anthropic",
        anthropic_api_key="sk", advanced_model="claude-unknown",
    )  # fmt: skip
    build_adapters(s, problems=problems)
    assert any("가격을 몰라" in p for p in problems)


# ── 설정 API ────────────────────────────────────────────


@pytest.fixture
async def api(orch, store, tmp_path):
    import httpx

    from app.adapters.registry import build_adapters
    from app.config import Settings
    from app.main import create_app

    settings = Settings(_env_file=None, data_dir=store.data_dir, gemini_api_key="g-key")
    orch.settings = settings
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_ADVANCED=off\nRENDER_PRESET=veryfast\n", encoding="utf-8")
    app = create_app(settings, orch, env_path=env_path)

    def rebuild(a):
        a.state.setup_problems = problems = []
        return build_adapters(settings, problems=problems)

    app.state.rebuild = rebuild
    seen = []

    def models_handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.headers["x-api-key"] != "sk-ant-good-123456":
            return httpx2.Response(401, json={"type": "error", "error": {"message": "bad"}})
        return httpx2.Response(
            200,
            json={
                "data": [{"type": "model", "id": "claude-opus-5-5", "display_name": "Opus",
                          "created_at": "2026-01-01T00:00:00Z"}],
                "has_more": False, "first_id": "claude-opus-5-5", "last_id": "claude-opus-5-5",
            },
        )  # fmt: skip

    app.state.anthropic_http_client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(models_handler)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        c.settings, c.env_path, c.seen = settings, env_path, seen
        yield c


async def test_anthropic_key_check_is_free_model_list(api):
    r = await api.post("/settings/keys/check", json={"ANTHROPIC_API_KEY": "sk-ant-good-123456"})
    assert r.json()["results"]["ANTHROPIC_API_KEY"]["ok"] is True
    assert api.seen[-1].url.path == "/v1/models"  # 토큰을 쓰지 않는 조회
    r = await api.post("/settings/keys/check", json={"ANTHROPIC_API_KEY": "sk-ant-bad-1234567"})
    res = r.json()["results"]["ANTHROPIC_API_KEY"]
    assert res["ok"] is False and "sk-ant-bad" not in r.text


async def test_advanced_needs_consent_and_key(api):
    r = await api.post("/settings/advanced", json={"mode": "anthropic", "accept_cost": False})
    assert r.status_code == 422 and "동의" in r.text
    r = await api.post("/settings/advanced", json={"mode": "anthropic", "accept_cost": True})
    assert r.status_code == 422 and "키" in r.text
    assert "LLM_ADVANCED=off" in api.env_path.read_text(encoding="utf-8")


async def test_advanced_on_and_off(api):
    await api.post("/settings/keys", json={"values": {"ANTHROPIC_API_KEY": "sk-ant-good-123456"}})
    r = await api.post(
        "/settings/advanced",
        json={
            "mode": "anthropic", "model": "claude-sonnet-5-5", "effort": "low",
            "daily_budget_usd": 0.5, "accept_cost": True,
        },
    )  # fmt: skip
    assert r.status_code == 200, r.text
    text = api.env_path.read_text(encoding="utf-8")
    assert "LLM_ADVANCED=anthropic" in text and "ADVANCED_MODEL=claude-sonnet-5-5" in text
    assert "ADVANCED_DAILY_BUDGET_USD=0.5" in text and "RENDER_PRESET=veryfast" in text
    cfg = (await api.get("/config")).json()
    assert cfg["advanced"]["model"] == "claude-sonnet-5-5"
    assert cfg["advanced"]["budget_usd"] == 0.5 and cfg["advanced"]["used_usd"] == 0
    status = (await api.get("/settings/keys")).json()
    assert status["advanced"]["mode"] == "anthropic"
    assert "sk-ant-good" not in json.dumps(status)

    r = await api.post("/settings/advanced", json={"mode": "off"})
    assert r.status_code == 200
    assert (await api.get("/config")).json()["advanced"] is None
    text = api.env_path.read_text(encoding="utf-8")
    assert "LLM_ADVANCED=off" in text
    assert "ADVANCED_MODEL=claude-sonnet-5-5" in text  # 끌 때 고른 모델은 그대로 둔다
    assert (await api.get("/settings/keys")).json()["advanced"]["model"] == "claude-sonnet-5-5"


async def test_advanced_rejects_unknown_model(api):
    api.settings.anthropic_api_key = "sk-ant-good-123456"
    r = await api.post(
        "/settings/advanced",
        json={"mode": "anthropic", "model": "gpt-x", "accept_cost": True},
    )
    assert r.status_code == 422
