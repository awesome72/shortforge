"""Pixabay 무료 사진 어댑터 (IMAGE_MODE의 stock 또는 pixabay, D12).

Pexels가 신규 API 키 발급을 중단해(2026-10 확인) 기본 사진 소스를 Pixabay로 바꿨다.
API 약관 (pixabay.com/api/docs, 2026-10 확인):
- 무료 키(가입 후 문서 페이지에 표시), 키당 60초에 100회. 넘으면 429
- 검색 요청은 24시간 캐시해야 한다 → app.cache로 24시간 캐시
- 이미지를 영구적으로 직접 링크(hotlink)하면 안 된다 → 내려받아 프로젝트 폴더에 둔다
- 출처 표기를 요청한다 → credit에 남겨 UI에 표시
"""

from __future__ import annotations

from pathlib import Path

import httpx

from app.adapters.base import ImageAdapter, ImageQuotaExceeded, ImageRequest, ImageResult
from app.cache import Cache

SEARCH = "https://pixabay.com/api/"
CACHE_TTL = 24 * 3600  # 약관: 검색 요청은 24시간 캐시
PER_PAGE = 20


class PixabayError(RuntimeError):
    pass


class PixabayAdapter(ImageAdapter):
    wants_english_prompts = True

    def __init__(
        self, api_key: str, cache: Cache, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        if not api_key:
            raise PixabayError(
                "PIXABAY_API_KEY가 비어 있다 — pixabay.com 가입 후 "
                "pixabay.com/api/docs/ 에서 key를 복사한다"
            )
        self.api_key = api_key
        self.cache = cache
        self.client = httpx.AsyncClient(timeout=30, transport=transport)
        self._used: set[int] = set()  # 같은 실행에서 같은 사진을 두 장면에 쓰지 않는다

    async def _search(self, query: str) -> list[dict]:
        key = f"pixabay:{query.lower()}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        params = {
            "key": self.api_key,
            "q": query,
            "image_type": "photo",
            "orientation": "vertical",
            "safesearch": "true",
            "per_page": PER_PAGE,
        }
        try:
            r = await self.client.get(SEARCH, params=params)
        except httpx.TransportError as e:
            raise PixabayError(f"Pixabay에 연결할 수 없다: {e}") from e
        if r.status_code == 429:
            raise ImageQuotaExceeded("Pixabay 요청 한도(60초에 100회) 초과")
        if r.status_code != 200:
            # 잘못된 키는 400과 "[ERROR 400] Invalid or missing API key" 같은 본문을 준다
            raise PixabayError(f"Pixabay 검색 실패 HTTP {r.status_code}: {r.text[:200]}")
        hits = r.json().get("hits", [])
        self.cache.set(key, hits, CACHE_TTL)
        return hits

    async def generate(self, req: ImageRequest) -> ImageResult | None:
        query = (req.query or req.prompt).strip()[:100]  # q는 최대 100자
        hits = await self._search(query)
        if not hits:
            return None  # 검색 결과 없음 → 체인의 다음 소스
        fresh = [h for h in hits if h["id"] not in self._used] or hits
        hit = fresh[req.seed % len(fresh)]
        self._used.add(hit["id"])

        src = hit.get("largeImageURL") or hit["webformatURL"]  # 최대 1280px
        try:
            img = await self.client.get(src, follow_redirects=True)
        except httpx.TransportError as e:
            raise PixabayError(f"Pixabay 이미지를 받을 수 없다: {e}") from e
        img.raise_for_status()
        out = req.out_path.with_suffix(Path(src.split("?")[0]).suffix or ".jpg")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(img.content)
        credit = f"Image by {hit.get('user', 'unknown')} from Pixabay · {hit.get('pageURL', '')}"
        return ImageResult(path=out, source="stock", provider="pixabay", credit=credit)
