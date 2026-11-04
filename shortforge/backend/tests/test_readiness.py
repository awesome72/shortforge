"""내용 조건(이미지·음성이 빈 장면)과 지금 설정에 맞춘 안내, 단계별 LLM 처리 기록."""

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.readiness import image_hint, no_generator_hint, unused_image_sources


def settings(**kw):
    return Settings(_env_file=None, **kw)


def test_hint_points_to_keys_the_user_already_has():
    up = {"image_mode": "upload"}
    cf = settings(cloudflare_account_id="acc", cloudflare_api_token="tok", **up)
    assert "'AI 생성'으로 바꾸고 5단계를 다시 해 주세요" in image_hint(cf)
    px = settings(pixabay_api_key="pix-123", **up)
    assert "'무료 사진'으로 바꾸고" in image_hint(px)
    none = settings(**up)
    assert "키를 넣고 방식을 바꾼 뒤" in image_hint(none)
    assert "사진 교체" in image_hint(none)
    # 소스가 있는데 이미지를 못 받은 경우는 '다른 이미지'를 안내한다
    assert "다른 이미지" in image_hint(settings(image_mode="cloudflare,stock"))
    # 고른 방식의 키가 없으면 '본인 사진만'이라고 하지 않고 키를 안내한다
    stock = settings(image_mode="stock")
    assert "본인 사진만" not in no_generator_hint(stock) and "키" in no_generator_hint(stock)
    assert no_generator_hint(none) == image_hint(none)


def test_unused_image_sources():
    s = settings(
        cloudflare_account_id="acc",
        cloudflare_api_token="tok",
        pixabay_api_key="pix-123",
        image_mode="upload",
    )
    assert unused_image_sources(s) == ["Cloudflare AI 생성", "Pixabay 무료 사진"]
    s.image_mode = "cloudflare,stock"
    assert unused_image_sources(s) == []


async def test_api_reports_not_ready_and_unused_keys(orch, store, adapters, sample_input):
    async def no_image(*args, **kwargs):
        return None

    adapters.image.generate = no_image
    orch.settings.pixabay_api_key = "pix-123"  # 키는 있는데 이미지 방식은 upload
    orch.settings.image_mode = "upload"
    p = await orch.run_all(store.create(sample_input).id)
    app = create_app(orch.settings, orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        body = (await c.get(f"/projects/{p.id}")).json()
        assert "'무료 사진'으로 바꾸고" in body["not_ready"]["s6"]
        assert body["blockers"]["s6"] == []
        r = await c.post(f"/projects/{p.id}/steps/s6/run")
        assert r.status_code == 409 and "그림이 없는 장면" in r.json()["detail"]
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
    # 컨셉(경량)이 먼저 불린다
    assert sorted(s4.providers) == ["anthropic", "gemini"] and "claude-sonnet-5-5" in s4.models
    assert s4.usd == pytest.approx(0.02)
    assert p.llm_usage["s1"].providers == ["gemini"] and p.llm_usage["s1"].usd == 0
    assert "s5" not in p.llm_usage or p.llm_usage["s5"].providers == ["gemini"]
    assert "s7" not in p.llm_usage  # LLM을 쓰지 않는 단계


def test_auto_uses_whatever_free_keys_exist():
    """기본값 auto: 키를 넣기만 하면 방식을 바꾸지 않아도 그림을 만든다 (첫 실행의 막다른 길)."""
    from app.adapters.registry import build_image

    none = settings()
    assert none.image_mode == "auto" and none.image_sources == []
    assert "키가 아직 없어요" in image_hint(none)
    assert not build_image(none).wants_english_prompts  # 본인 사진으로 동작

    keys = {"cloudflare_account_id": "acc", "cloudflare_api_token": "tok"}
    assert settings(**keys).image_sources == ["cloudflare"]
    both = settings(pixabay_api_key="pix-123", **keys)
    assert both.image_sources == ["cloudflare", "stock"]
    assert unused_image_sources(both) == []  # 키가 있는 소스는 모두 쓴다
    assert build_image(both).wants_english_prompts
    # Cloudflare 값이 하나만 있으면 쓰지 않는다 (키 오류 배너 대신 무료 사진으로)
    assert settings(cloudflare_account_id="acc", pixabay_api_key="p").image_sources == ["stock"]
    with pytest.raises(ValueError):
        settings(image_mode="auto,stock")


async def test_config_follows_keys_in_auto(orch, store, sample_input):
    """auto의 소스 목록은 지금 가진 키를 따른다 (키 저장·재조립은 test_keys)."""
    app = create_app(orch.settings, orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        cfg = (await c.get("/config")).json()
        assert cfg["image_mode"] == "auto" and cfg["image_sources"] == []
        orch.settings.pixabay_api_key = "pix-123"
        cfg = (await c.get("/config")).json()
        assert cfg["image_sources"] == ["stock"] and cfg["image_unused"] == []
