"""내용 조건(이미지·음성이 빈 장면)과 지금 설정에 맞춘 안내, 단계별 LLM 처리 기록."""

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.readiness import image_hint, unused_image_sources


def settings(**kw):
    return Settings(_env_file=None, **kw)


def test_hint_points_to_keys_the_user_already_has():
    cf = settings(cloudflare_account_id="acc", cloudflare_api_token="tok")
    assert "'AI 생성'으로 바꾸고 5단계를 다시 실행한다" in image_hint(cf)
    px = settings(pixabay_api_key="pix-123")
    assert "'무료 사진'으로 바꾸고" in image_hint(px)
    none = settings()
    assert "키를 넣고 방식을 바꾼 뒤" in image_hint(none)
    assert "사진 교체" in image_hint(none)
    # 소스가 있는데 이미지를 못 받은 경우는 '다른 이미지'를 안내한다
    assert "다른 이미지" in image_hint(settings(image_mode="cloudflare,stock"))


def test_unused_image_sources():
    s = settings(cloudflare_account_id="acc", cloudflare_api_token="tok", pixabay_api_key="pix-123")
    assert unused_image_sources(s) == ["Cloudflare AI 생성", "Pixabay 무료 사진"]
    s.image_mode = "cloudflare,stock"
    assert unused_image_sources(s) == []


async def test_api_reports_not_ready_and_unused_keys(orch, store, adapters, sample_input):
    async def no_image(*args, **kwargs):
        return None

    adapters.image.generate = no_image
    orch.settings.pixabay_api_key = "pix-123"  # 키는 있는데 이미지 방식은 upload
    p = await orch.run_all(store.create(sample_input).id)
    app = create_app(orch.settings, orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        body = (await c.get(f"/projects/{p.id}")).json()
        assert "'무료 사진'으로 바꾸고" in body["not_ready"]["s6"]
        assert body["blockers"]["s6"] == []
        r = await c.post(f"/projects/{p.id}/steps/s6/run")
        assert r.status_code == 409 and "이미지가 없는 장면" in r.json()["detail"]
        cfg = (await c.get("/config")).json()
        assert cfg["image_unused"] == ["Pixabay 무료 사진"]
    assert "'무료 사진'으로 바꾸고" in " ".join(p.warnings["s5"])


async def test_llm_usage_records_models_and_cost(orch, store, adapters, sample_input):
    from app.metrics import record_llm_call

    original = adapters.llm.generate_json

    async def recording(task, *args, **kwargs):
        paid = task == "s4_strategy"
        record_llm_call(
            task=task,
            provider="anthropic" if paid else "gemini",
            model="claude-sonnet-5-5" if paid else "gemini-lite",
            sec=0.1,
            waited=0.0,
            ok=True,
            **({"usd": 0.02} if paid else {}),
        )
        return await original(task, *args, **kwargs)

    adapters.llm.generate_json = recording
    p = await orch.run_all(store.create(sample_input).id, from_step="s1")
    s4 = p.llm_usage["s4"]
    # 전략은 유료 모델, 짧은 대사 보강(s4_lengthen)은 무료 경량 모델
    assert s4.providers == ["anthropic", "gemini"] and s4.models[0] == "claude-sonnet-5-5"
    assert s4.usd == pytest.approx(0.02)
    assert p.llm_usage["s1"].providers == ["gemini"] and p.llm_usage["s1"].usd == 0
    assert "s5" not in p.llm_usage or p.llm_usage["s5"].providers == ["gemini"]
    assert "s7" not in p.llm_usage  # LLM을 쓰지 않는 단계
