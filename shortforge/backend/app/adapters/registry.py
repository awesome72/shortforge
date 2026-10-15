"""설정값으로 어댑터 묶음을 만든다. 실제 엔진은 각 Step에서 등록한다.

| 어댑터 | 설정 | 구현 Step |
|---|---|---|
| youtube | (단일) | Step 3 |
| llm | LLM_MODE=gemini|ollama | Step 4 |
| tts | TTS_MODE=edge|melo | Step 2 / Step 7 |
| image | IMAGE_MODE=upload|comfyui | Step 5 / Step 8 |
| video | (FFmpeg) | Step 2 |
"""

from __future__ import annotations

from app.adapters.base import Adapters
from app.adapters.fake import fake_adapters
from app.config import Settings


def build_adapters(settings: Settings, *, fake: bool = False) -> Adapters:
    if fake:
        return fake_adapters()
    raise NotImplementedError(
        "실제 어댑터는 아직 없다 (Step 2~5에서 구현). 지금은 build_adapters(..., fake=True)를 쓴다."
    )
