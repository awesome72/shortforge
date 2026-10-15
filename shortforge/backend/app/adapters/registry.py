"""설정값으로 어댑터 묶음을 만든다.

| 어댑터 | 설정 | 상태 |
|---|---|---|
| youtube | YOUTUBE_API_KEY | ✅ (Step 3) |
| llm | LLM_MODE=gemini|ollama | ✅ (Step 4) |
| tts | TTS_MODE=edge|melo | edge ✅ (Step 2), melo는 Step 7 |
| image | IMAGE_MODE=upload|comfyui | ✅ (comfyui는 원격 GPU 장비, Step 8) |
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
    if settings.image_mode == "upload":
        from app.adapters.image.upload import UploadImageAdapter

        return UploadImageAdapter()
    from app.adapters.image.comfyui import ComfyUIAdapter

    return ComfyUIAdapter(
        settings.comfyui_url,
        workflow_path=settings.comfyui_workflow or None,
    )


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

        return GeminiAdapter(settings.gemini_api_key, settings.gemini_model)
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
