"""키가 비어 있어도 API 서버가 뜨고, 무엇을 채울지 알려 준다 (베타 첫 실행)."""

import pytest

from app.adapters.image.upload import UploadImageAdapter
from app.adapters.registry import SetupRequired, build_adapters
from app.config import Settings


def empty_keys(tmp_path, **extra):
    return Settings(
        gemini_api_key="",
        youtube_api_key="",
        llm_mode="gemini",
        data_dir=tmp_path,
        **extra,
    )


def test_strict_build_still_fails_without_keys(tmp_path):
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        build_adapters(empty_keys(tmp_path))


async def test_lenient_build_collects_problems_and_defers_errors(tmp_path):
    problems: list[str] = []
    adapters = build_adapters(empty_keys(tmp_path), problems=problems)
    assert any("GEMINI_API_KEY" in p for p in problems)
    assert any("YOUTUBE_API_KEY" in p for p in problems)
    with pytest.raises(SetupRequired, match="GEMINI_API_KEY"):
        await adapters.llm.generate_json("s1_keywords", "s", "u", dict)
    with pytest.raises(SetupRequired, match="YOUTUBE_API_KEY"):
        await adapters.youtube.search("q")


def test_lenient_image_chain_drops_sources_without_keys(tmp_path):
    problems: list[str] = []
    settings = empty_keys(
        tmp_path,
        image_mode="cloudflare,stock",
        cloudflare_account_id="",
        cloudflare_api_token="",
        pixabay_api_key="",
    )
    adapters = build_adapters(settings, problems=problems)
    assert isinstance(adapters.image, UploadImageAdapter)  # 남은 소스가 없으면 본인 사진만
    assert any("'cloudflare'" in p for p in problems)
    assert any("'stock'" in p for p in problems)


async def test_dev_fake_all_builds_only_fakes(tmp_path):
    """화면 자동 테스트(CI)용: 키·FFmpeg 없이 모든 어댑터가 Fake다."""
    from app.adapters.fake import FakeLLM, FakeVideo, FakeYouTube
    from app.main import create_app

    app = create_app(Settings(_env_file=None, data_dir=tmp_path, dev_fake_all=True))
    async with app.router.lifespan_context(app):
        adapters = app.state.orch.adapters
        assert app.state.setup_problems == []
    assert isinstance(adapters.llm, FakeLLM) and isinstance(adapters.youtube, FakeYouTube)
    assert isinstance(adapters.video, FakeVideo)
