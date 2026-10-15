from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.base import VideoInfo
from app.scoring import build_refs, zscores

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def video(vid, ch, views, likes=0, days=10):
    return VideoInfo(
        video_id=vid,
        title=vid,
        channel_id=ch,
        views=views,
        likes=likes,
        comments=0,
        duration_sec=30,
        published_at=NOW - timedelta(days=days),
        thumbnail_url="",
    )


def test_zscores_edge_cases():
    assert zscores([]) == []
    assert zscores([1.0]) == [0.0]
    assert zscores([2.0, 2.0]) == [0.0, 0.0]
    assert zscores([None, 1.0, 3.0]) == [0.0, -1.0, 1.0]


def test_small_channel_beats_big_channel():
    # 발표 자료 예시: 소규모 A(1.2만 구독, 184만 조회) vs 대형 D(41만 구독, 390만 조회)
    vids = [video("A", "a", 1_840_000, likes=60_000), video("D", "d", 3_900_000, likes=90_000)]
    refs = build_refs(vids, {"a": 12_000, "d": 410_000}, NOW)
    assert refs[0].video_id == "A"
    assert refs[0].ratio_views_per_sub == pytest.approx(153.333, rel=1e-3)


def test_hidden_subscribers_and_min_subs():
    vids = [video("H", "hidden", 1000), video("T", "tiny", 1000)]
    refs = {r.video_id: r for r in build_refs(vids, {"hidden": None, "tiny": 5}, NOW)}
    assert refs["H"].ratio_views_per_sub is None
    assert refs["T"].ratio_views_per_sub == 10.0  # max(subs, 100)


def test_views_per_day_floor_one_day():
    refs = build_refs([video("N", "c", 500, days=0)], {"c": 1000}, NOW)
    assert refs[0].views_per_day == 500.0
