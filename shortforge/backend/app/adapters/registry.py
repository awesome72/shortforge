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
    YouTubeAdapter,
)
from app.adapters.fake import FakeLLM, fake_adapters
from app.config import Settings


class AdapterNotAvailable(NotImplementedError):
    pass


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


def build_image(settings: Settings) -> ImageAdapter:
    """IMAGE_MODE의 소스를 순서대로 체인에 넣는다. upload만 있으면 생성하지 않는다."""
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
    }
    return ImageChain([(name, builders[name](settings)) for name in settings.image_sources])


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
        workers=settings.render_workers or None,
    )


def build_llm(settings: Settings) -> LLMAdapter:
    if settings.llm_mode == "gemini":
        from app.adapters.llm.gemini import GeminiAdapter

        return GeminiAdapter(
            settings.gemini_api_key,
            settings.gemini_model,
            light_model=settings.gemini_model_light or None,
        )
    from app.adapters.llm.ollama import OllamaAdapter

    return OllamaAdapter(settings.ollama_host, settings.ollama_model)


def build_adapters(settings: Settings, *, fake: bool = False, fake_llm: bool = False) -> Adapters:
    """fake=True: 전부 Fake. fake_llm=True: LLM만 Fake (렌더·YouTube 측정 스크립트용)."""
    if fake:
        return fake_adapters()
    return Adapters(
        llm=FakeLLM() if fake_llm else build_llm(settings),
        youtube=build_youtube(settings),
        tts=build_tts(settings),
        image=build_image(settings),
        video=build_video(settings),
    )
