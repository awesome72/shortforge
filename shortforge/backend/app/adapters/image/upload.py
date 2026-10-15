"""IMAGE_MODE=upload: 이미지를 생성하지 않는다 (D4). 프롬프트만 남기고 사용자가 사진을 올린다."""

from __future__ import annotations

from pathlib import Path

from app.adapters.base import ImageAdapter


class UploadImageAdapter(ImageAdapter):
    async def generate(self, prompt: str, negative: str, seed: int, out_path: Path) -> None:
        return None
