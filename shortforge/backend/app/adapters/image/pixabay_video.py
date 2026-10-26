"""Pixabay 무료 동영상 어댑터 (장면 소스 동영상, IMAGE_MODE의 video 또는 5단계 '영상 후보').

API 약관 (pixabay.com/api/docs, 2026-10 확인):
- 사진과 같은 키, 키당 60초에 100회. 넘으면 429
- 검색 요청은 24시간 캐시해야 한다 → app.cache로 24시간 캐시
- 출처 표기를 요청한다 → credit에 남겨 5단계와 업로드 체크리스트에 표시
- 동영상 검색에는 세로(orientation) 필터가 없다 → 세로 영상을 먼저 고르고, 없으면 가로 영상의
  가운데를 9:16으로 자른다. 1080p 가로를 자르면 폭이 608px라 흐려져 4K(large)를 먼저 쓴다

받은 원본은 바로 1080×1920·30fps·소리 없는 짧은 클립으로 한 번 변환해 둔다(conform).
4K 원본을 렌더 때마다 풀면 RAM 8GB·GPU 없는 PC에서 느리고, 화면 미리보기도 무거워진다.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from app.adapters.base import ImageAdapter, ImageQuotaExceeded, ImageRequest, ImageResult
from app.cache import Cache
from app.media import find_exe, run

SEARCH = "https://pixabay.com/api/videos/"
CACHE_TTL = 24 * 3600  # 약관: 검색 요청은 24시간 캐시
PER_PAGE = 20
MIN_SEC = 4  # 장면 하나(보통 4~6초)를 채울 수 있는 영상만
MAX_SEC = 60
LARGE_MAX_BYTES = 80 * 1024 * 1024  # 4K가 이보다 크면 1080p를 받는다
MAX_CLIP_SEC = 20  # 변환할 때 앞부분만 남긴다 (장면은 길어야 10초 안팎)
OUT_W, OUT_H, OUT_FPS = 1080, 1920, 30


class PixabayVideoError(RuntimeError):
    pass


def is_vertical(hit: dict) -> bool:
    v = hit.get("videos", {}).get("medium", {})
    return v.get("height", 0) > v.get("width", 0)


def pick_rendition(hit: dict) -> dict:
    """세로 영상이면 1080p(이미 세로), 가로면 4K를 받아 자른다(너무 크면 1080p)."""
    videos = hit.get("videos", {})
    large, medium = videos.get("large") or {}, videos.get("medium") or {}
    if not is_vertical(hit) and large.get("url") and 0 < large.get("size", 0) <= LARGE_MAX_BYTES:
        return large
    return medium if medium.get("url") else large


def rank(hits: list[dict]) -> list[dict]:
    """길이가 맞는 영상만, 세로 영상을 앞에 둔다 (검색 순서는 유지)."""
    usable = [h for h in hits if MIN_SEC <= h.get("duration", 0) <= MAX_SEC]
    return sorted(usable, key=lambda h: not is_vertical(h))


class PixabayVideoAdapter(ImageAdapter):
    wants_english_prompts = True

    def __init__(
        self,
        api_key: str,
        cache: Cache,
        transport: httpx.AsyncBaseTransport | None = None,
        skip_person: bool = True,
    ) -> None:
        if not api_key:
            raise PixabayVideoError(
                "PIXABAY_API_KEY가 비어 있다 — pixabay.com 가입 후 "
                "pixabay.com/api/docs/ 에서 key를 복사한다"
            )
        self.api_key = api_key
        self.cache = cache
        self.client = httpx.AsyncClient(timeout=120, transport=transport)
        self._used: set[int] = set()  # 같은 실행에서 같은 영상을 두 장면에 쓰지 않는다
        # 체인에서는 주인공 장면을 건너뛴다(같은 주인공 유지). 5단계 '영상 후보'는 사용자가 고른다
        self.skip_person = skip_person

    async def _search(self, query: str) -> list[dict]:
        key = f"pixabay-video:{query.lower()}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        params = {
            "key": self.api_key,
            "q": query,
            "video_type": "film",
            "safesearch": "true",
            "per_page": PER_PAGE,
        }
        try:
            r = await self.client.get(SEARCH, params=params)
        except httpx.TransportError as e:
            raise PixabayVideoError(f"Pixabay에 연결할 수 없다: {e}") from e
        if r.status_code == 429:
            raise ImageQuotaExceeded("Pixabay 요청 한도(60초에 100회) 초과")
        if r.status_code != 200:
            raise PixabayVideoError(f"Pixabay 동영상 검색 HTTP {r.status_code}: {r.text[:200]}")
        hits = r.json().get("hits", [])
        self.cache.set(key, hits, CACHE_TTL)
        return hits

    async def generate(self, req: ImageRequest) -> ImageResult | None:
        if req.person and self.skip_person:
            return None  # 주인공 장면 → 체인의 다음 소스(AI 생성)
        query = (req.query or req.prompt).strip()[:100]  # q는 최대 100자
        hits = rank(await self._search(query))
        if not hits:
            return None  # 맞는 영상 없음 → 체인의 다음 소스
        fresh = [h for h in hits if h["id"] not in self._used] or hits
        hit = fresh[req.seed % len(fresh)]
        self._used.add(hit["id"])

        out = req.out_path.with_suffix(".mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        raw = out.with_name(out.stem + ".src.mp4")
        try:
            await self._download(pick_rendition(hit)["url"], raw)
            await conform(raw, out)
        finally:
            raw.unlink(missing_ok=True)
        credit = f"Video by {hit.get('user', 'unknown')} from Pixabay · {hit.get('pageURL', '')}"
        return ImageResult(path=out, source="stock", provider="pixabay-video", credit=credit)

    async def _download(self, url: str, dest: Path) -> None:
        try:
            async with self.client.stream("GET", url, follow_redirects=True) as r:
                r.raise_for_status()
                with dest.open("wb") as f:
                    async for chunk in r.aiter_bytes(1024 * 1024):
                        f.write(chunk)
        except httpx.HTTPError as e:
            dest.unlink(missing_ok=True)
            raise PixabayVideoError(f"Pixabay 동영상을 받을 수 없다: {e}") from e


async def conform(src: Path, out: Path) -> Path:
    """원본 → 세로 1080×1920, 30fps, 소리 없음, 앞 MAX_CLIP_SEC초 (가운데를 잘라 낸다)."""
    part = out.with_name(out.stem + ".part.mp4")
    await run(
        [find_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(src), "-t", str(MAX_CLIP_SEC),
         "-vf", f"fps={OUT_FPS},scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
                f"crop={OUT_W}:{OUT_H},setsar=1,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an",
         "-movflags", "+faststart", str(part)],
    )  # fmt: skip
    os.replace(part, out)
    return out
