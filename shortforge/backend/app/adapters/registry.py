"""설정값으로 어댑터 묶음을 만든다.

| 어댑터 | 설정 | 상태 |
|---|---|---|
| youtube | YOUTUBE_API_KEY | ✅ (Step 3) |
| llm | LLM_MODE=gemini|ollama | ✅ (Step 4) |
| tts | TTS_MODE=edge|melo | edge ✅ (Step 2), melo는 Step 7 |
| image | IMAGE_MODE=upload 또는 cloudflare,stock,comfyui 순서 | ✅ 체인 (D12) |
| video | FFmpeg | ✅ (Step 2) |
"""

from __future__ import annotations

from app.adapters.base import (
    Adapters,
    ImageAdapter,
    LLMAdapter,
    TTSAdapter,
    VideoAdapter,
    VideoGenAdapter,
    YouTubeAdapter,
)
from app.adapters.fake import FakeLLM, FakeVideoGen, fake_adapters
from app.config import Settings


class AdapterNotAvailable(NotImplementedError):
    pass


class SetupRequired(RuntimeError):
    """.env 설정이 빠져 이 어댑터를 쓸 수 없다. 단계를 실행하면 이 메시지가 그대로 보인다."""


class _MissingLLM(LLMAdapter):
    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def generate_json(self, *args, **kwargs):
        raise SetupRequired(self.reason)


class _MissingYouTube(YouTubeAdapter):
    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def search(self, *args, **kwargs):
        raise SetupRequired(self.reason)

    async def videos(self, *args, **kwargs):
        raise SetupRequired(self.reason)

    async def channels(self, *args, **kwargs):
        raise SetupRequired(self.reason)

    async def trending(self, *args, **kwargs):
        raise SetupRequired(self.reason)

    async def top_comments(self, *args, **kwargs):
        raise SetupRequired(self.reason)


def build_youtube(settings: Settings) -> YouTubeAdapter:
    from app.adapters.youtube.api import YouTubeDataAdapter
    from app.cache import Cache
    from app.quota import QuotaMeter

    return YouTubeDataAdapter(
        settings.youtube_api_key,
        Cache(settings.db_path),
        QuotaMeter(settings.db_path, settings.youtube_daily_unit_limit),
    )


def build_tts(settings: Settings) -> TTSAdapter:
    if settings.tts_mode == "edge":
        from app.adapters.tts.edge import EdgeTTSAdapter

        return EdgeTTSAdapter()
    raise AdapterNotAvailable(f"TTS_MODE={settings.tts_mode}는 아직 없다 (Step 7)")


def build_image(settings: Settings, problems: list[str] | None = None) -> ImageAdapter:
    """IMAGE_MODE의 소스를 순서대로 체인에 넣는다. upload만 있으면 생성하지 않는다.

    problems가 주어지면 키가 빠진 소스는 빼고 그 이유를 problems에 남긴다.
    """
    if not settings.image_sources:
        from app.adapters.image.upload import UploadImageAdapter

        return UploadImageAdapter()
    from app.adapters.image.chain import ImageChain

    builders = {
        "cloudflare": _cloudflare,
        "stock": _pixabay,  # 무료 사진 기본 소스 (Pexels는 신규 키 발급 중단)
        "pixabay": _pixabay,
        "pexels": _pexels,
        "comfyui": _comfyui,
        "video": pixabay_video,
    }
    sources = []
    for name in settings.image_sources:
        try:
            sources.append((name, builders[name](settings)))
        except RuntimeError as e:
            if problems is None:
                raise
            problems.append(f"이미지 소스 '{name}'를 쓰지 않는다: {e}")
    if not sources:
        from app.adapters.image.upload import UploadImageAdapter

        return UploadImageAdapter()
    return ImageChain(sources)


def pixabay_video(settings: Settings, skip_person: bool = True, transport=None) -> ImageAdapter:
    """Pixabay 무료 동영상. skip_person이면 주인공이 나오는 장면은 건너뛴다(체인용).

    transport는 테스트의 가짜 서버(httpx.MockTransport)다.
    """
    from app.adapters.image.pixabay_video import PixabayVideoAdapter
    from app.cache import Cache

    return PixabayVideoAdapter(
        settings.pixabay_api_key,
        Cache(settings.db_path),
        transport=transport,
        skip_person=skip_person,
    )


def _cloudflare(settings: Settings) -> ImageAdapter:
    from app.adapters.image.cloudflare import CloudflareImageAdapter, NeuronMeter

    return CloudflareImageAdapter(
        settings.cloudflare_account_id,
        settings.cloudflare_api_token,
        NeuronMeter(settings.db_path, settings.cloudflare_daily_neurons),
        model=settings.cloudflare_image_model,
    )


def _pixabay(settings: Settings) -> ImageAdapter:
    from app.adapters.image.pixabay import PixabayAdapter
    from app.cache import Cache

    return PixabayAdapter(settings.pixabay_api_key, Cache(settings.db_path))


def _pexels(settings: Settings) -> ImageAdapter:
    from app.adapters.image.pexels import PexelsAdapter

    return PexelsAdapter(settings.pexels_api_key)


def _comfyui(settings: Settings) -> ImageAdapter:
    from app.adapters.image.comfyui import ComfyUIAdapter

    return ComfyUIAdapter(settings.comfyui_url, workflow_path=settings.comfyui_workflow or None)


def build_video(settings: Settings) -> VideoAdapter:
    from app.adapters.video.ffmpeg import FFmpegRenderer

    return FFmpegRenderer(
        preset=settings.render_preset,
        font=settings.subtitle_font,
        grade=settings.render_grade,
        brand=settings.brand_name,
        workers=settings.render_workers or None,
    )


def build_video_gen(
    settings: Settings, problems: list[str] | None = None
) -> VideoGenAdapter | None:
    """장면 그림 → 영상 (D19). 켜지 않으면 만들지 않는다: 기본 경로에는 유료 호출이 없다."""
    if settings.video_gen == "off":
        return None
    if not settings.hf_token:
        # 영상과 상관없는 실행까지 막지 않는다 (CLI에서도 그냥 빠진다)
        if problems is not None:
            problems.append(
                "영상 만들기를 쓰려면 Hugging Face 토큰이 필요해요 (설정 → 영상 만들기)"
            )
        return None
    from app.adapters.video_gen.hf import HFVideoGen
    from app.spend import VIDEO_PROVIDER, SpendMeter

    spend = SpendMeter(settings.db_path, settings.video_gen_daily_budget_usd, VIDEO_PROVIDER)
    return HFVideoGen(settings.hf_token, spend)


def build_llm(settings: Settings, problems: list[str] | None = None) -> LLMAdapter:
    """기본(무료) LLM. 고급 모드(D13)가 켜지면 지정한 작업만 유료 모델로 보내는 라우터로 감싼다."""
    base = _build_base_llm(settings)
    if settings.llm_advanced == "off":
        return base
    try:
        return _with_advanced(settings, base)
    except RuntimeError as e:
        if problems is None:
            raise
        problems.append(str(e))  # 고급 모드만 빠지고 무료 경로는 그대로 쓴다
        return base


def _with_advanced(settings: Settings, base: LLMAdapter) -> LLMAdapter:
    from app.adapters.llm.routed import RoutedLLM
    from app.spend import DEFAULT_MODEL, SpendMeter, price_for

    provider = settings.llm_advanced
    model = settings.advanced_model or DEFAULT_MODEL[provider]
    price = price_for(provider, model)
    if price is None:  # 가격을 모르면 하루 예산을 지킬 수 없다
        raise RuntimeError(f"고급 모드 모델 '{model}'의 가격을 몰라 쓰지 않는다 (app/spend.py)")
    spend = SpendMeter(settings.db_path, settings.advanced_daily_budget_usd)
    # 유료 SDK는 여기서만 지연 import한다 (기본 설정에서는 로드되지 않음, test_cost_guard)
    advanced: LLMAdapter
    if provider == "anthropic":
        from app.adapters.llm.advanced.anthropic_api import AnthropicAdapter

        advanced = AnthropicAdapter(
            settings.anthropic_api_key, model, effort=settings.advanced_effort, spend=spend
        )
    else:  # OpenAI·OpenRouter는 같은 OpenAI 호환 어댑터
        from app.adapters.llm.advanced.openai_compat import OpenAICompatAdapter

        advanced = OpenAICompatAdapter(
            provider,
            getattr(settings, f"{provider}_api_key"),
            model,
            effort=settings.advanced_effort,
            spend=spend,
        )
    return RoutedLLM(base, advanced, settings.advanced_task_set, spend, label=price.label)


def _build_base_llm(settings: Settings) -> LLMAdapter:
    if settings.llm_mode == "gemini":
        from app.adapters.llm.gemini import GeminiAdapter

        return GeminiAdapter(
            settings.gemini_api_key,
            settings.gemini_model,
            light_model=settings.gemini_model_light or None,
            thinking_level=settings.gemini_thinking_level,
        )
    from app.adapters.llm.ollama import OllamaAdapter

    return OllamaAdapter(settings.ollama_host, settings.ollama_model)


def build_adapters(
    settings: Settings,
    *,
    fake: bool = False,
    fake_llm: bool = False,
    problems: list[str] | None = None,
) -> Adapters:
    """fake=True: 전부 Fake. fake_llm=True: LLM만 Fake (렌더·YouTube 측정 스크립트용).

    problems가 주어지면(API 서버) 키가 비어 있어도 멈추지 않는다. 빠진 어댑터는 실행할 때
    SetupRequired를 내는 대체물로 두고, 이유를 problems에 모아 화면에 보여 준다.
    """
    if fake:
        adapters = fake_adapters()
        if settings.video_gen != "off":  # 화면 확인용: 버튼은 뜨고 비용은 들지 않는다
            adapters.video_gen = FakeVideoGen()
        return adapters

    def lenient(build, missing):
        try:
            if build is build_llm:
                return build(settings, problems)
            return build(settings)
        except RuntimeError as e:
            if problems is None:
                raise
            problems.append(str(e))
            return missing(str(e))

    adapters = Adapters(
        llm=FakeLLM() if fake_llm else lenient(build_llm, _MissingLLM),
        youtube=lenient(build_youtube, _MissingYouTube),
        tts=build_tts(settings),
        image=build_image(settings, problems),
        video=build_video(settings),
        video_gen=build_video_gen(settings, problems),
    )
    # 무료 동영상 소스는 썸네일 판정에 같은 LLM(경량 모델)을 쓴다
    for name, source in getattr(adapters.image, "sources", []):
        if name == "video":
            source.llm = adapters.llm
    return adapters
