"""S2 레퍼런스 탐색: 구독자 대비 상위 숏폼 (F-2.1~F-2.3).

캐시(24h)와 쿼터 미터(F-2.4)는 Step 3에서 YouTube 어댑터 쪽에 붙인다.
"""

from __future__ import annotations

from datetime import timedelta

from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Input, Ref, utcnow
from app.scoring import build_refs

LOOKBACK_DAYS = 90
SEARCH_MAX_RESULTS = 25
TOP_N = 10
DEFAULT_SELECTED = 4


async def run(ctx: StepContext) -> list[Ref]:
    inp: Input = ctx.read("input")
    if not inp.keywords:
        raise StepInputError("검색 키워드가 없다 — S1을 먼저 실행하거나 키워드를 입력한다")

    yt = ctx.adapters.youtube
    now = utcnow()
    since = now - timedelta(days=LOOKBACK_DAYS)

    ids: list[str] = []
    for i, kw in enumerate(inp.keywords):
        await ctx.progress(f"search:{kw}", i / len(inp.keywords))
        for vid in await yt.search(kw, inp.region, inp.lang, since, SEARCH_MAX_RESULTS):
            if vid not in ids:
                ids.append(vid)
    if not ids:
        raise StepInputError("검색 결과가 없다 — 키워드를 바꿔 본다")

    videos = await yt.videos(ids)
    max_len = ctx.settings.ref_max_duration_sec
    videos = [v for v in videos if v.duration_sec <= max_len]
    if not videos:
        raise StepInputError(f"{max_len}초 이하 영상이 없다")

    channels = await yt.channels(sorted({v.channel_id for v in videos}))
    subs = {c.channel_id: c.subs for c in channels}

    refs = build_refs(videos, subs, now)[:TOP_N]
    for r in refs[:DEFAULT_SELECTED]:
        r.selected = True
    hidden = sum(1 for r in refs if r.subs is None)
    if hidden:
        ctx.warn(f"구독자 수를 숨긴 채널의 영상 {hidden}개는 구독자 대비 배수 없이 점수를 매겼다")
    return refs
