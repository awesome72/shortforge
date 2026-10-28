"""YouTube Data API v3 어댑터 (S2·S3).

모든 호출은 캐시 확인 → 쿼터 확인 → 호출 → 쿼터 기록 순서다.
- search.list는 (keyword, region, lang, PT 날짜) 단위로 24시간 캐시한다.
- videos/channels/commentThreads는 항목 단위로 24시간 캐시한다. 같은 날 재실행하면 0 units다.
- 레퍼런스 미디어는 받지 않는다. 메타데이터·통계·공개 댓글·썸네일 URL만 쓴다 (제약 5).
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

import httpx

from app.adapters.base import ChannelInfo, VideoInfo, YouTubeAdapter
from app.cache import Cache
from app.quota import QuotaExceeded, QuotaMeter, pt_today

BASE = "https://www.googleapis.com/youtube/v3"
TTL = 24 * 3600
TRENDING_TTL = 6 * 3600  # 인기 영상은 하루에도 바뀐다
BATCH = 50
RETRIES = 2


class YouTubeAPIError(RuntimeError):
    pass


def parse_duration(iso: str) -> int:
    """ISO 8601 기간(PT1M5S, P0D 등) → 초."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class YouTubeDataAdapter(YouTubeAdapter):
    def __init__(
        self,
        api_key: str,
        cache: Cache,
        quota: QuotaMeter,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise YouTubeAPIError(
                "YOUTUBE_API_KEY가 비어 있다 — 설정 화면(또는 shortforge/.env)에 넣는다"
            )
        self.api_key = api_key
        self.cache = cache
        self.quota = quota
        self.client = httpx.AsyncClient(base_url=BASE, timeout=20, transport=transport)

    async def aclose(self) -> None:
        await self.client.aclose()

    # ── 공통 호출 ────────────────────────────────────────

    async def _get(self, method: str, params: dict) -> dict:
        self.quota.check(method)
        last: Exception | None = None
        for attempt in range(RETRIES + 1):
            try:
                resp = await self.client.get(f"/{method}", params={**params, "key": self.api_key})
            except httpx.TransportError as e:  # 요청이 서버에 닿지 않았으면 쿼터를 쓰지 않는다
                last = e
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            self.quota.record(method)
            if resp.status_code < 400:
                return resp.json()
            reason = _reason(resp)
            if reason in ("quotaExceeded", "dailyLimitExceeded"):
                raise QuotaExceeded(f"YouTube가 쿼터 초과를 알렸다 ({reason})")
            if resp.status_code >= 500 and attempt < RETRIES:
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            raise _APIError(method, resp.status_code, reason, resp)
        raise YouTubeAPIError(f"{method} 네트워크 오류: {last}")

    # ── YouTubeAdapter ───────────────────────────────────

    async def search(
        self, keyword: str, region: str, lang: str, published_after: datetime, max_results: int
    ) -> list[str]:
        key = f"yt:search:{keyword.strip().lower()}|{region}|{lang}|{max_results}|{pt_today()}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        data = await self._get(
            "search",
            {
                "part": "id",
                "q": keyword,
                "type": "video",
                "videoDuration": "short",  # 4분 미만. 60초 이하 필터는 S2에서 한다
                "order": "viewCount",
                "publishedAfter": _rfc3339(published_after),
                "regionCode": region,
                "relevanceLanguage": lang,
                "maxResults": max_results,
            },
        )
        ids = [
            it["id"]["videoId"] for it in data.get("items", []) if it.get("id", {}).get("videoId")
        ]
        self.cache.set(key, ids, TTL)
        return ids

    async def videos(self, ids: list[str]) -> list[VideoInfo]:
        raw = await self._batched("videos", ids, "part", "snippet,statistics,contentDetails")
        return [_video(raw[i]) for i in ids if i in raw]

    async def channels(self, ids: list[str]) -> list[ChannelInfo]:
        raw = await self._batched("channels", ids, "part", "statistics")
        out = []
        for cid in ids:
            if cid not in raw:
                continue
            st = raw[cid].get("statistics", {})
            hidden = st.get("hiddenSubscriberCount") or "subscriberCount" not in st
            out.append(
                ChannelInfo(channel_id=cid, subs=None if hidden else int(st["subscriberCount"]))
            )
        return out

    async def top_comments(self, video_id: str, max_results: int = 100) -> list[str]:
        key = f"yt:comments:{video_id}|{max_results}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        try:
            data = await self._get(
                "commentThreads",
                {
                    "part": "snippet",
                    "videoId": video_id,
                    "order": "relevance",
                    "maxResults": max_results,
                    "textFormat": "plainText",
                },
            )
        except _APIError as e:
            if e.reason in ("commentsDisabled", "videoNotFound", "forbidden"):
                self.cache.set(key, [], TTL)
                return []
            raise
        comments = [
            it["snippet"]["topLevelComment"]["snippet"].get("textDisplay", "")
            for it in data.get("items", [])
        ]
        self.cache.set(key, comments, TTL)
        return comments

    async def trending(self, region: str, category: str | None = None) -> list[VideoInfo]:
        """많이 본 영상 50개 (1 unit, 6시간 캐시). 지원하지 않는 분류면 빈 목록."""
        key = f"yt:trending:{region}|{category or ''}"
        cached = self.cache.get(key)
        if cached is not None:
            return [VideoInfo.model_validate(v) for v in cached]
        params = {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": region,
            "maxResults": BATCH,
        }
        if category:
            params["videoCategoryId"] = category
        try:
            data = await self._get("videos", params)
        except _APIError as e:
            if e.reason in ("notFound", "videoChartNotFound", "invalidCategoryId"):
                self.cache.set(key, [], TRENDING_TTL)
                return []
            raise
        videos = [_video(it) for it in data.get("items", [])]
        self.cache.set(key, [v.model_dump(mode="json") for v in videos], TRENDING_TTL)
        return videos

    # ── 내부 ─────────────────────────────────────────────

    async def _batched(self, method: str, ids: list[str], *part: str) -> dict[str, dict]:
        """항목 단위 캐시를 먼저 보고, 없는 ID만 50개씩 묶어 조회한다."""
        ids = list(dict.fromkeys(ids))
        keys = {i: f"yt:{method}:{i}" for i in ids}
        hit = self.cache.get_many(list(keys.values()))
        found = {i: hit[k] for i, k in keys.items() if k in hit}
        missing = [i for i in ids if i not in found]
        for start in range(0, len(missing), BATCH):
            chunk = missing[start : start + BATCH]
            data = await self._get(
                method, {part[0]: part[1], "id": ",".join(chunk), "maxResults": BATCH}
            )
            items = {it["id"]: it for it in data.get("items", [])}
            self.cache.set_many({keys[i]: items[i] for i in items if i in keys}, TTL)
            found.update(items)
        return found


class _APIError(YouTubeAPIError):
    def __init__(self, method: str, status: int, reason: str, resp: httpx.Response) -> None:
        self.reason = reason
        msg = ""
        try:
            msg = resp.json()["error"]["message"]
        except Exception:
            pass
        super().__init__(f"{method} 실패 HTTP {status} ({reason}) {msg}".strip())


def _reason(resp: httpx.Response) -> str:
    try:
        errors = resp.json()["error"].get("errors") or [{}]
        return errors[0].get("reason", "")
    except Exception:
        return ""


def _video(it: dict) -> VideoInfo:
    sn, st, cd = it.get("snippet", {}), it.get("statistics", {}), it.get("contentDetails", {})
    thumbs = sn.get("thumbnails", {})
    thumb = next((thumbs[k]["url"] for k in ("high", "medium", "default") if k in thumbs), "")
    return VideoInfo(
        video_id=it["id"],
        title=sn.get("title", ""),
        description=sn.get("description", ""),
        tags=sn.get("tags", []),
        channel_id=sn.get("channelId", ""),
        views=int(st.get("viewCount", 0)),
        likes=int(st.get("likeCount", 0)),  # 좋아요 비공개면 0
        comments=int(st.get("commentCount", 0)),
        duration_sec=parse_duration(cd.get("duration", "")),
        published_at=datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")),
        thumbnail_url=thumb,
    )
