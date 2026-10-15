"""레퍼런스 점수 (PRD §9, PROJECT_PROMPT §7 S2).

score = 0.5·z(log ratio) + 0.3·z(log vpd) + 0.2·z(like_rate)
- ratio = views / max(subs, 100), 숨김 구독자면 None → 해당 항은 0(평균)으로 둔다
- vpd   = views / max(경과일, 1)
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime

from app.adapters.base import VideoInfo
from app.schemas.project import Ref

WEIGHTS = (0.5, 0.3, 0.2)
MIN_SUBS = 100


def zscores(values: list[float | None]) -> list[float]:
    """None은 0으로. 표본이 2개 미만이거나 분산이 0이면 모두 0."""
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return [0.0] * len(values)
    mean = statistics.fmean(present)
    sd = statistics.pstdev(present)
    if sd == 0:
        return [0.0] * len(values)
    return [0.0 if v is None else (v - mean) / sd for v in values]


def build_refs(videos: list[VideoInfo], subs: dict[str, int | None], now: datetime) -> list[Ref]:
    """지표를 계산하고 점수 내림차순으로 정렬한 Ref 목록 (selected는 모두 False)."""
    ratios: list[float | None] = []
    vpds: list[float] = []
    like_rates: list[float] = []
    for v in videos:
        s = subs.get(v.channel_id)
        ratios.append(None if s is None else v.views / max(s, MIN_SUBS))
        days = max((now - v.published_at).total_seconds() / 86400, 1.0)
        vpds.append(v.views / days)
        like_rates.append(v.likes / v.views if v.views else 0.0)

    z_r = zscores([None if r is None else math.log(max(r, 1e-9)) for r in ratios])
    z_v = zscores([math.log(max(x, 1e-9)) for x in vpds])
    z_l = zscores(list(like_rates))

    refs = []
    for i, v in enumerate(videos):
        score = WEIGHTS[0] * z_r[i] + WEIGHTS[1] * z_v[i] + WEIGHTS[2] * z_l[i]
        refs.append(
            Ref(
                video_id=v.video_id,
                title=v.title,
                channel_id=v.channel_id,
                subs=subs.get(v.channel_id),
                views=v.views,
                likes=v.likes,
                comments=v.comments,
                duration_sec=v.duration_sec,
                published_at=v.published_at,
                ratio_views_per_sub=None if ratios[i] is None else round(ratios[i], 3),
                views_per_day=round(vpds[i], 1),
                like_rate=round(like_rates[i], 4),
                score=round(score, 4),
                thumbnail_url=v.thumbnail_url,
                fetched_at=now,
            )
        )
    refs.sort(key=lambda r: r.score, reverse=True)
    return refs
