"""설정값으로 어댑터 묶음을 만든다.

| 어댑터 | 설정 | 상태 |
|---|---|---|
| youtube | (단일) | Step 3 |
| llm | LLM_MODE=gemini|ollama | Step 4 |
| tts | TTS_MODE=edge|melo | edge ✅ (Step 2), melo는 Step 7 |
| image | IMAGE_MODE=upload|comfyui | upload ✅, comfyui는 Step 8 |
| video | FFmpeg | ✅ (Step 2) |

아직 없는 어댑터는 fake_missing=True일 때 Fake로 채운다 (개발·스파이크용).
"""

from __future__ import annotations

from app.adapters.base import Adapters, ImageAdapter, TTSAdapter, VideoAdapter
from app.adapters.fake import FakeLLM, FakeYouTube, fake_adapters
from app.config import Settings


class AdapterNotAvailable(NotImplementedError):
    pass


def build_tts(settings: Settings) -> TTSAdapter:
    if settings.tts_mode == "edge":
        from app.adapters.tts.edge import EdgeTTSAdapter

        return EdgeTTSAdapter()
    raise AdapterNotAvailable(f"TTS_MODE={settings.tts_mode}는 아직 없다 (Step 7)")


def build_image(settings: Settings) -> ImageAdapter:
    if settings.image_mode == "upload":
        from app.adapters.image.upload import UploadImageAdapter

        return UploadImageAdapter()
    raise AdapterNotAvailable(f"IMAGE_MODE={settings.image_mode}는 아직 없다 (Step 8)")


def build_video(settings: Settings) -> VideoAdapter:
    from app.adapters.video.ffmpeg import FFmpegRenderer

    return FFmpegRenderer(
        preset=settings.render_preset,
        font=settings.subtitle_font,
        workers=settings.render_workers or None,
    )


def build_adapters(
    settings: Settings, *, fake: bool = False, fake_missing: bool = False
) -> Adapters:
    if fake:
        return fake_adapters()
    if not fake_missing:
        raise AdapterNotAvailable("LLM(Step 4)·YouTube(Step 3) 어댑터가 아직 없다")
    return Adapters(
        llm=FakeLLM(),
        youtube=FakeYouTube(),
        tts=build_tts(settings),
        image=build_image(settings),
        video=build_video(settings),
    )
