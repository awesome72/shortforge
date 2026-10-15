"""IMAGE_MODE=upload: 이미지를 생성하지 않는다 (D4). 프롬프트만 남기고 사용자가 사진을 올린다."""

from __future__ import annotations

from app.adapters.base import ImageAdapter, ImageRequest


class UploadImageAdapter(ImageAdapter):
    async def generate(self, req: ImageRequest) -> None:
        return None
