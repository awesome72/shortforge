"""Pixabay 무료 동영상 (장면 소스 동영상). 가짜 서버만 쓰고, 변환(FFmpeg)은 복사로 바꾼다."""

import shutil

import httpx
import pytest

from app.adapters.base import ImageQuotaExceeded, ImageRequest
from app.adapters.image import pixabay_video
from app.adapters.image.pixabay_video import PixabayVideoAdapter, choose, pick_rendition, rank
from app.adapters.registry import build_image
from app.cache import Cache
from app.config import Settings
from app.image_prompt import has_person

MP4 = b"\x00\x00\x00\x18ftypmp42fake-video"


def hit(i, w, h, duration=12, large_size=40_000_000, tags="city, night, street"):
    base = f"https://cdn.pixabay.com/video/{i}"
    return {
        "id": i,
        "duration": duration,
        "tags": tags,
        "user": f"user{i}",
        "pageURL": f"https://pixabay.com/videos/x-{i}/",
        "videos": {
            "large": {
                "url": f"{base}_large.mp4",
                "width": w * 2,
                "height": h * 2,
                "size": large_size,
            },
            "medium": {"url": f"{base}_medium.mp4", "width": w, "height": h, "size": 9_000_000},
        },
    }


class FakePixabayVideo:
    def __init__(self, hits=None, status=200):
        self.hits = hits if hits is not None else [hit(1, 1920, 1080), hit(2, 1080, 1920)]
        self.status = status
        self.searches: list[httpx.Request] = []
        self.downloads: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/videos/":
            self.searches.append(request)
            if self.status != 200:
                return httpx.Response(self.status, text="error")
            return httpx.Response(200, json={"total": len(self.hits), "hits": self.hits})
        self.downloads.append(request.url.path)
        return httpx.Response(200, content=MP4)


@pytest.fixture(autouse=True)
def no_ffmpeg(monkeypatch):
    async def copy(src, out):
        shutil.copyfile(src, out)
        return out

    monkeypatch.setattr(pixabay_video, "conform", copy)


def adapter(tmp_path, server, **kw):
    return PixabayVideoAdapter(
        "pkey", Cache(tmp_path / "db.sqlite"), transport=httpx.MockTransport(server), **kw
    )


def req(tmp_path, seed=0, prompt="city street at night, neon lights", person=False):
    return ImageRequest(prompt, "", seed, tmp_path / "S2", query="city night", person=person)


def test_rank_by_tags_and_people_penalty():
    """사람이 없는 장면: 검색어가 태그에 많은 영상, 사람 태그가 없는 영상을 먼저 고른다."""
    hits = [
        hit(1, 1080, 1920, tags="laptop, notebook, man, work"),  # 세로지만 사람·노트북 컴퓨터
        hit(2, 1920, 1080, tags="notebook, coffee, desk, morning"),
        hit(3, 1920, 1080, tags="flowers, garden"),  # 검색어와 겹치지 않는다
    ]
    assert [h["id"] for h in rank(hits, "notebook coffee desk")] == [2]  # 사람 영상은 빠진다
    # 주인공 장면(사용자가 고르는 후보)이면 사람 감점이 없다: 겹치는 단어 수로만
    assert [h["id"] for h in rank(hits, "notebook man", person=True)] == [1, 2]
    # 아무것도 겹치지 않으면 모두 남기되 사람 영상은 맨 뒤로
    assert [h["id"] for h in rank(hits, "ocean waves")] == [2, 3, 1]


def test_rank_prefers_focused_tags_and_drops_off_topic():
    hits = [
        hit(1, 1920, 1080, tags="christmas, gift, cozy, living room, holiday, home, merry, eve"),
        hit(2, 1920, 1080, tags="ruins, house, burnt, living room"),
        hit(3, 1920, 1080, tags="fireplace, living room, cozy, warm, home"),
        hit(4, 1920, 1080, tags="cat, sofa, living room, interior, couch, relax, animal, fluffy"),
    ]
    # 같은 점수(3)면 태그가 검색어 중심인 3번이 먼저, 크리스마스·폐허는 감점으로 뒤로
    assert [h["id"] for h in rank(hits, "cozy living room")][:2] == [3, 4]
    # 검색어에 있으면 감점하지 않는다
    assert [h["id"] for h in rank(hits, "christmas living room")][0] == 1


def test_rank_prefers_vertical_and_usable_length():
    hits = [hit(1, 1920, 1080), hit(2, 1080, 1920), hit(3, 1080, 1920, duration=2)]
    assert [h["id"] for h in rank(hits)] == [2, 1]  # 2초짜리는 장면을 못 채운다


def test_landscape_downloads_4k_unless_too_big():
    assert pick_rendition(hit(1, 1920, 1080))["url"].endswith("_large.mp4")  # 잘라도 선명하게
    assert pick_rendition(hit(1, 1920, 1080, large_size=200_000_000))["url"].endswith("_medium.mp4")
    assert pick_rendition(hit(2, 1080, 1920))["url"].endswith("_medium.mp4")  # 이미 세로


async def test_search_download_credit_and_cache(tmp_path):
    server = FakePixabayVideo()
    res = await adapter(tmp_path, server).generate(req(tmp_path))
    assert res.path == tmp_path / "S2.mp4" and res.path.read_bytes() == MP4
    assert not (tmp_path / "S2.src.mp4").exists()  # 원본은 변환 뒤 지운다
    assert res.source == "stock" and res.provider == "pixabay-video"
    assert res.credit == "Video by user2 from Pixabay · https://pixabay.com/videos/x-2/"
    q = server.searches[0].url.params
    assert q["q"] == "city night" and q["video_type"] == "film" and q["safesearch"] == "true"
    assert server.downloads == ["/video/2_medium.mp4"]  # 세로 영상을 먼저
    await adapter(tmp_path, server).generate(req(tmp_path, seed=1))
    assert len(server.searches) == 1  # 약관: 검색은 24시간 캐시


async def test_person_scenes_are_skipped_in_the_chain(tmp_path):
    server = FakePixabayVideo()
    assert await adapter(tmp_path, server).generate(req(tmp_path, person=True)) is None
    assert server.searches == []  # 주인공 장면은 검색도 하지 않는다
    manual = adapter(tmp_path, server, skip_person=False)  # 5단계 '영상 후보'는 사용자가 고른다
    assert await manual.generate(req(tmp_path, person=True)) is not None


async def test_no_results_and_rate_limit(tmp_path):
    assert await adapter(tmp_path, FakePixabayVideo(hits=[])).generate(req(tmp_path)) is None
    with pytest.raises(ImageQuotaExceeded):
        # 결과 없음도 24시간 캐시되므로 다른 DB로 확인한다
        (tmp_path / "b").mkdir()
        await adapter(tmp_path / "b", FakePixabayVideo(status=429)).generate(req(tmp_path))


def test_has_person():
    assert has_person("a Korean woman in her 50s writing in a notebook")
    assert has_person("an elderly person walking")
    assert not has_person("a notebook and a coffee cup on a wooden desk, morning light")


def test_video_token_in_image_mode():
    s = Settings(_env_file=None, image_mode="video,stock", pixabay_api_key="k")
    chain = build_image(s)
    assert [name for name, _ in chain.sources] == ["video", "stock"]
    assert type(chain.sources[0][1]).__name__ == "PixabayVideoAdapter"


def test_choose_takes_the_top_three_for_consecutive_seeds():
    ranked = [hit(i, 1080, 1920) for i in range(1, 6)]
    used: set[int] = set()
    picks = []
    for seed in (31, 32, 33):  # 후보 3개 = seed+1..+3
        h = choose(ranked, seed, used)
        used.add(h["id"])
        picks.append(h["id"])
    assert sorted(picks) == [1, 2, 3]  # 상위 3개를 빠짐없이
    assert choose(ranked, 31, used)["id"] == 4  # 모두 썼으면 다음 순위
