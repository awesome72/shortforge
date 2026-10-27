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
import re
from pathlib import Path

import httpx

from app.adapters.base import (
    ImageAdapter,
    ImageQuotaExceeded,
    ImageRequest,
    ImageResult,
    LLMAdapter,
)
from app.cache import Cache
from app.image_prompt import is_illustrated
from app.media import find_exe, run
from app.video_pick import judge, thumbnail

SEARCH = "https://pixabay.com/api/videos/"
CACHE_TTL = 24 * 3600  # 약관: 검색 요청은 24시간 캐시
PER_PAGE = 50  # 관련도로 다시 고르므로 넉넉히 (24시간 캐시라 요청 수는 같다)
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


# 사람이 나오는 영상의 태그. 사람이 없는 장면에서는 뒤로 미룬다
# (2026-10 실측: "notebook coffee desk"가 노트북 컴퓨터를 쓰는 사람 영상만 3개 골랐다)
PERSON_TAGS = {
    "man", "men", "woman", "women", "people", "person", "girl", "boy", "businessman",
    "businesswoman", "lady", "guy", "student", "worker", "child", "kid", "portrait", "face",
    "family", "couple", "friend", "lifestyle", "model", "selfie",
}  # fmt: skip
PERSON_PENALTY = 2
# 검색어에 없으면 장면 분위기를 해치는 태그
# (2026-10 실측: "cozy living room"에 크리스마스·폐허 영상)
OFF_TOPIC_TAGS = {
    "christmas", "xmas", "santa", "halloween", "easter", "ruin", "burnt", "burned",
    "abandoned", "horror", "war",
}  # fmt: skip
OFF_TOPIC_PENALTY = 2
TOP_K = 3  # 관련도 상위 몇 개 안에서 고를지 (seed가 다르면 그 안에서 다른 영상)


def _words(text: str) -> set[str]:
    """비교용 단어: 소문자, 3자 이상, 끝의 복수형 s를 뗀다."""
    out = set()
    for w in re.findall(r"[a-z]+", text.lower()):
        if len(w) >= 3:
            out.add(w[:-1] if w.endswith("s") and len(w) > 3 else w)
    return out


# 태그와 같은 규칙(복수형 s 떼기)으로 맞춘다: "christmas"는 "christma"로 비교된다
_PERSON = _words(" ".join(PERSON_TAGS))
_OFF_TOPIC = _words(" ".join(OFF_TOPIC_TAGS))


def relevance(hit: dict, query: str, person: bool) -> tuple[int, float]:
    """(점수, 정밀도). 점수 = 태그에 있는 검색어 단어 수 − 감점,
    정밀도 = 그 단어가 태그에서 차지하는 비율.

    사람 없는 장면인데 사람 태그가 있거나, 검색어에 없는 행사·폐허 태그가 있으면 감점한다.
    태그를 잔뜩 단 영상보다 검색어 중심으로 태그를 단 영상이 장면에 잘 맞는다.
    """
    tags = _words(hit.get("tags", ""))
    wanted = _words(query)
    matched = len(wanted & tags)
    score = matched
    if not person and tags & _PERSON:
        score -= PERSON_PENALTY
    if (tags & _OFF_TOPIC) - wanted:
        score -= OFF_TOPIC_PENALTY
    return score, matched / len(tags) if tags else 0.0


def choose(ranked: list[dict], seed: int, used: set[int]) -> dict:
    """순위 목록의 seed % TOP_K 자리부터 아직 쓰지 않은 영상을 차례로 찾는다.

    쓴 영상을 먼저 빼고 자리를 고르면 자리가 밀려 상위 영상을 건너뛴다(후보 3개가 1·3·5위).
    """
    start = seed % min(len(ranked), TOP_K)
    for h in ranked[start:] + ranked[:start]:
        if h["id"] not in used:
            return h
    return ranked[start]


def credit(hit: dict) -> str:
    return f"Video by {hit.get('user', 'unknown')} from Pixabay · {hit.get('pageURL', '')}"


def preview(hit: dict) -> dict:
    """화면 미리보기용: 작은 영상은 Pixabay 주소로 바로 재생한다(약관상 직접 재생 허용).

    고르기 전에는 내려받지 않는다 — 후보 3개를 모두 4K로 받아 바꾸던 때는 장면당 24~47초가 걸렸다.
    """
    videos = hit.get("videos", {})
    small = videos.get("tiny") or videos.get("small") or videos.get("medium") or {}
    return {
        "id": hit["id"],
        "preview": small.get("url", ""),
        "thumbnail": thumbnail(hit),
        "duration": hit.get("duration", 0),
        "vertical": is_vertical(hit),
        "credit": credit(hit),
    }


def rank(hits: list[dict], query: str = "", person: bool = False) -> list[dict]:
    """길이가 맞는 영상만 관련도 순으로 (같으면 세로 영상, 그다음 검색 순서).

    관련도가 0보다 큰 영상이 있으면 그것만 남긴다(태그가 검색어와 하나도 겹치지 않는 영상은 뺀다).
    """
    usable = [h for h in hits if MIN_SEC <= h.get("duration", 0) <= MAX_SEC]
    scored = [(*relevance(h, query, person), i, h) for i, h in enumerate(usable)]
    if any(score > 0 for score, *_ in scored):
        scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: (-x[0], -x[1], not is_vertical(x[3]), x[2]))
    return [h for *_, h in scored]


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
        # 썸네일 판정(app/video_pick)에 쓸 무료 경량 LLM. build_adapters가 넣는다(없으면 태그 순서)
        self.llm: LLMAdapter | None = None

    async def _search(self, query: str) -> list[dict]:
        key = f"pixabay-video:{PER_PAGE}:{query.lower()}"
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
        if self.skip_person and (req.person or is_illustrated(req.prompt)):
            # 주인공 장면, 또는 그림체가 일러스트·수채화인 프로젝트 → 체인의 다음 소스(AI 생성).
            # 그림 사이에 실사 영상이 끼면 톤이 따로 논다(2026-10 실측).
            # 5단계 '영상 후보'는 사용자가 고른다
            return None
        hits = await self.candidates(req.query or req.prompt, req.prompt, req.person)
        if not hits:
            return None  # 맞는 영상 없음 → 체인의 다음 소스
        hit = choose(hits, req.seed, self._used)
        self._used.add(hit["id"])
        return await self.fetch(hit, req.out_path)

    async def candidates(self, query: str, scene: str, person: bool) -> list[dict]:
        """검색(24시간 캐시) → 태그 순위 → 썸네일 판정 순서로 줄 세운 영상들."""
        query = query.strip()[:100]  # q는 최대 100자
        hits = rank(await self._search(query), query, person)
        return await judge(self.llm, hits, scene or query, person_ok=person)

    async def find(self, query: str, video_id: int) -> dict | None:
        """고른 영상을 검색 결과(캐시)에서 다시 찾는다."""
        hits = await self._search(query.strip()[:100])
        return next((h for h in hits if h.get("id") == video_id), None)

    async def fetch(self, hit: dict, out_path: Path) -> ImageResult:
        """영상을 받아 세로 1080×1920으로 한 번 변환한다. 이미 받은 파일이면 그대로 쓴다."""
        out = out_path.with_suffix(".mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            raw = out.with_name(out.stem + ".src.mp4")
            try:
                await self._download(pick_rendition(hit)["url"], raw)
                await conform(raw, out)
            finally:
                raw.unlink(missing_ok=True)
        return ImageResult(path=out, source="stock", provider="pixabay-video", credit=credit(hit))

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
