"""단계 실패 종류: 화면이 이유에 맞는 안내와 다음 행동을 고르는 근거."""

import re
from pathlib import Path

import httpx
import pytest
from google.genai import errors

from app.adapters.llm.common import LLMOutputError
from app.adapters.llm.gemini import GeminiAdapter, GeminiQuotaExhausted, GeminiRequestError
from app.adapters.registry import SetupRequired
from app.adapters.youtube.api import _APIError
from app.failure import KINDS, failure_kind
from app.media import MediaError, RenderStalled
from app.orchestrator import INTERRUPTED, StepInputError
from app.quota import QuotaExceeded
from app.schemas.project import BusinessBrief, Input, StepState
from tests.test_llm import FakeGenAI, KeywordsOut


def wrapped(cause: BaseException) -> Exception:
    try:
        try:
            raise cause
        except BaseException as e:
            raise RuntimeError("밖의 오류") from e
    except RuntimeError as outer:
        return outer


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (GeminiQuotaExhausted("x"), "llm_quota"),
        (GeminiRequestError("x", "llm_busy"), "llm_busy"),
        (GeminiRequestError("x"), ""),
        (SetupRequired("x"), "setup"),
        (QuotaExceeded("x"), "youtube_quota"),
        (LLMOutputError("x"), "llm_output"),
        (MediaError("x"), "media"),
        (RenderStalled("x"), "render_stall"),
        (StepInputError("x", "no_refs"), "no_refs"),
        (StepInputError("x"), ""),
        (httpx.ConnectError("x"), "network"),
        (ConnectionResetError("x"), "network"),
        (ValueError("x"), ""),
    ],
)
def test_kinds(error, kind):
    assert failure_kind(error) == kind


def test_finds_the_cause_and_inside_a_task_group():
    assert failure_kind(wrapped(QuotaExceeded("x"))) == "youtube_quota"
    group = ExceptionGroup("묶음", [ValueError("a"), MediaError("b")])
    assert failure_kind(group) == "media"


def test_a_known_kind_beats_a_network_cause():
    e = GeminiRequestError("x", "llm_busy")
    e.__cause__ = TimeoutError()
    assert failure_kind(e) == "llm_busy"


async def test_step_failure_records_kind_and_rerun_clears_it(orch, adapters, sample_input):
    p = orch.create_project(sample_input)

    async def no_quota(*args, **kwargs):
        raise QuotaExceeded("오늘 한도")

    original = adapters.youtube.search
    adapters.youtube.search = no_quota
    await orch.run_step(p.id, "s1")
    p = await orch.run_step(p.id, "s2")
    assert p.status["s2"] == StepState.ERROR
    assert p.error_kinds["s2"] == "youtube_quota"

    adapters.youtube.search = original
    p = await orch.run_step(p.id, "s2")
    assert p.status["s2"] == StepState.DONE
    assert "s2" not in p.error_kinds


async def test_interrupted_step_is_marked(orch, store, sample_input):
    p = orch.create_project(sample_input)
    p.status["s2"] = StepState.RUNNING
    store.save(p, snapshot=False)
    orch.recover_interrupted()
    p = store.load(p.id)
    assert p.errors["s2"] == INTERRUPTED
    assert p.error_kinds["s2"] == "interrupted"


def test_every_kind_has_a_screen_message():
    ts = Path(__file__).parents[2] / "frontend/lib/failure.ts"
    body = ts.read_text(encoding="utf-8").split("FAILURES", 1)[1]
    assert set(re.findall(r"^  (\w+): \{", body, re.M)) == set(KINDS)


@pytest.mark.parametrize(
    ("reason", "body", "kind"),
    [
        ("keyInvalid", "{}", "setup"),
        ("badRequest", '{"error": {"message": "API key not valid"}}', "setup"),
        ("rateLimitExceeded", "{}", ""),
        ("forbidden", "{}", ""),
    ],
)
def test_youtube_errors(reason, body, kind):
    e = _APIError("search", 400, reason, httpx.Response(400, text=body))
    assert failure_kind(e) == kind


@pytest.mark.parametrize(
    ("code", "message", "kind"),
    [
        (400, "API key not valid. Please pass a valid API key.", "setup"),
        (403, "permission denied", "setup"),
        (402, "credits depleted", ""),
    ],
)
async def test_gemini_errors(code, message, kind):
    error = errors.ClientError(code, {"error": {"code": code, "message": message}})
    g = GeminiAdapter("", "m", client=FakeGenAI([error]))
    with pytest.raises(RuntimeError) as got:
        await g.generate_json("s1_keywords", "s", "u", KeywordsOut)
    assert failure_kind(got.value) == kind


async def test_shop_without_photos_asks_for_photos(orch):
    shop = BusinessBrief(
        shop_name="소담 분식", area="부천 상동", purpose="intro",
        product="김치볶음밥", action="네이버 지도에서 찾아 주세요",
    )  # fmt: skip
    p = orch.create_project(Input(topic="", mode="business", business=shop))
    p = await orch.run_all(p.id)
    assert p.error_kinds["s5"] == "need_photos"


async def test_edit_clears_the_kind(orch, adapters, sample_input):
    p = orch.create_project(sample_input)
    await orch.run_step(p.id, "s1")

    async def boom(*args, **kwargs):
        raise QuotaExceeded("한도")

    adapters.youtube.search = boom
    p = await orch.run_step(p.id, "s2")
    assert p.error_kinds["s2"] == "youtube_quota"
    p = await orch.edit(p.id, "input", p.input.model_copy(update={"topic": "다른 주제"}))
    assert "s2" not in p.error_kinds
