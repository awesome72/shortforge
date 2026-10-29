"""첫 화면의 '요즘 많이 보는 영상' (YouTube 인기 차트). 가짜 YouTube 서버만 쓴다."""

from datetime import UTC, datetime

import httpx
import pytest

from app.adapters.youtube.api import YouTubeDataAdapter
from app.cache import Cache
from app.config import Settings
from app.main import create_app
from app.quota import QuotaMeter


class ChartServer:
    def __init__(self, status=200, reason=""):
        self.requests: list[httpx.Request] = []
        self.status, self.reason = status, reason

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            err = {"error": {"message": self.reason, "errors": [{"reason": self.reason}]}}
            return httpx.Response(self.status, json=err)
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        items = [
            {
                "id": f"v{i}",
                "snippet": {"title": f"인기 {i}", "channelId": "ch", "publishedAt": now},
                "statistics": {"viewCount": str(1000 * (i + 1))},
                "contentDetails": {"duration": "PT45S" if i % 2 else "PT8M"},
            }
            for i in range(6)
        ]
        return httpx.Response(200, json={"items": items})


def adapter(tmp_path, server):
    quota = QuotaMeter(tmp_path / "q.db", daily_limit=8000)
    yt = YouTubeDataAdapter(
        "test-key", Cache(tmp_path / "q.db"), quota, httpx.MockTransport(server)
    )
    return yt, quota


async def test_trending_asks_the_chart_once_and_caches(tmp_path):
    server = ChartServer()
    yt, quota = adapter(tmp_path, server)
    videos = await yt.trending("KR", "26")
    q = server.requests[0].url.params
    assert q["chart"] == "mostPopular" and q["regionCode"] == "KR" and q["videoCategoryId"] == "26"
    assert len(videos) == 6 and quota.used() == 1  # videos.list 1회 = 1 unit
    again = await yt.trending("KR", "26")
    assert [v.video_id for v in again] == [v.video_id for v in videos]
    assert len(server.requests) == 1 and quota.used() == 1  # 6시간 캐시


async def test_unsupported_category_is_an_empty_cached_list(tmp_path):
    server = ChartServer(status=404, reason="videoChartNotFound")
    yt, _ = adapter(tmp_path, server)
    assert await yt.trending("KR", "99") == []
    assert await yt.trending("KR", "99") == [] and len(server.requests) == 1


@pytest.fixture
async def client(orch, store):
    app = create_app(Settings(_env_file=None, data_dir=store.data_dir), orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_endpoint_shows_a_notice_instead_of_failing(client, adapters):
    async def broken(*a, **k):
        raise RuntimeError("quotaExceeded")

    adapters.youtube.trending = broken
    r = await client.get("/trending")
    assert r.status_code == 200 and r.json()["videos"] == []
    assert "불러오지 못했어요" in r.json()["notice"]
    assert "quotaExceeded" not in r.json()["notice"] and r.json()["need_key"] is False


async def test_endpoint_asks_for_key_in_plain_words(client, adapters):
    from app.adapters.registry import SetupRequired

    async def missing(*a, **k):
        raise SetupRequired("YOUTUBE_API_KEY가 비어 있다 — .env")

    adapters.youtube.trending = missing
    body = (await client.get("/trending")).json()
    assert body["need_key"] is True and ".env" not in body["notice"]
