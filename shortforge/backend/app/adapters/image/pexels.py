"""Pexels 무료 사진 어댑터 (IMAGE_MODE에 stock, D12).

생성이 아니라 실제 사진을 검색해 쓴다. 무료 API 키, 기본 시간당 200회·월 20,000회.
상업 이용 가능, 출처 표기는 권장(의무 아님)이지만 credit을 남겨 UI에 표시한다.
주의: 얼굴이 식별되는 인물 사진은 상업 이용 시 초상권 문제가 있을 수 있다.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from app.adapters.base import ImageAdapter, ImageQuotaExceeded, ImageRequest, ImageResult

SEARCH = "https://api.pexels.com/v1/search"
PER_PAGE = 15


class PexelsError(RuntimeError):
    pass


class PexelsAdapter(ImageAdapter):
    wants_english_prompts = True

    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise PexelsError("PEXELS_API_KEY가 비어 있다 — pexels.com/api 에서 무료로 받는다")
        self.client = httpx.AsyncClient(
            timeout=30, transport=transport, headers={"Authorization": api_key}
        )
        self._used: set[int] = set()  # 같은 실행에서 같은 사진을 두 장면에 쓰지 않는다

    async def generate(self, req: ImageRequest) -> ImageResult | None:
        query = (req.query or req.prompt).strip()[:100]
        try:
            r = await self.client.get(
                SEARCH, params={"query": query, "orientation": "portrait", "per_page": PER_PAGE}
            )
        except httpx.TransportError as e:
            raise PexelsError(f"Pexels에 연결할 수 없다: {e}") from e
        if r.status_code == 429:
            raise ImageQuotaExceeded("Pexels 요청 한도(시간당 200회) 초과")
        if r.status_code != 200:
            raise PexelsError(f"Pexels 검색 실패 HTTP {r.status_code}: {r.text[:200]}")

        photos = r.json().get("photos", [])
        if not photos:
            return None  # 검색 결과 없음 → 체인의 다음 소스
        fresh = [p for p in photos if p["id"] not in self._used] or photos
        photo = fresh[req.seed % len(fresh)]
        self._used.add(photo["id"])

        src = photo["src"].get("portrait") or photo["src"]["large2x"]
        img = await self.client.get(src, follow_redirects=True)
        img.raise_for_status()
        out = req.out_path.with_suffix(Path(src.split("?")[0]).suffix or ".jpg")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(img.content)
        by = photo.get("photographer", "unknown")
        credit = f"Photo by {by} on Pexels · {photo.get('url', '')}"
        return ImageResult(path=out, source="stock", provider="pexels", credit=credit)
