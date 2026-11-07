"""S2 레퍼런스 탐색: 구독자 대비 상위 숏폼 (F-2.1~F-2.4). 한국과 해외 시장을 함께 찾는다.

순서: 시장별 search(+해외 인기 차트) → videos/channels 일괄 조회 → 길이 필터
→ 시장 안에서 점수 → LLM 관련성 판정·제목 번역 → 시장을 섞어 선택.
조회수 규모가 나라마다 달라 점수는 시장마다 따로 낸다.
캐시(24h)와 쿼터는 YouTube 어댑터가 맡는다.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from pydantic import BaseModel

from app.adapters.base import VideoInfo
from app.llm import load_prompt, wrap_untrusted
from app.modes import markets
from app.orchestrator import StepContext, StepInputError
from app.quota import QuotaExceeded
from app.schemas.project import Input, Ref, utcnow
from app.scoring import build_refs

log = logging.getLogger("app.steps.s2")

# 90일이면 좁은 주제는 조회수 1만 미만만 남았다(2026-10-31 실측: 재테크 6개 중 5개). 쿼터는 같다
LOOKBACK_DAYS = 180
SEARCH_MAX_RESULTS = 25
# search.list는 100 units. 합쳐서 4번(videos/channels·해외 인기 차트를 더해 약 410 units)까지
# 쓴다 (D16: S2 1회 ≤ 450 units). 해외를 찾지 않으면 지금처럼 키워드 3개를 쓴다
MAX_SEARCH_KEYWORDS = 3
MAX_SEARCHES = 4
MAX_WORLD_SEARCHES = 2
RELEVANCE_CANDIDATES = 20  # 점수 상위 몇 개를 관련성 판정에 넘길지 (해외를 찾지 않을 때)
TOP_N = 10
LOCAL_CANDIDATES = 14  # 해외도 찾을 때: 판정이 한 번에 너무 길어지지 않게 나눈다
WORLD_CANDIDATES = 6
TRENDING_CANDIDATES = 4  # 해외 인기 차트 (주제와 관련 있다고 판정된 것만 남긴다)
LOCAL_TOP = 8  # 화면에 보여 줄 후보 수
WORLD_TOP = 4
DEFAULT_SELECTED = 4  # 해외 후보가 없을 때
SELECT_LOCAL, SELECT_WORLD = 3, 3
MAX_PER_CHANNEL = 2  # 한 채널 영상이 분석을 채우지 않게
MIN_REF_VIEWS = 10_000  # 이보다 적으면 '터진 영상'의 근거가 되기 어렵다 (뒤로 보낸다)
MIN_REFS = 4  # 이보다 적으면 분석 근거가 빈약하다
TAGS_IN_PROMPT = 8


class RelevanceItem(BaseModel):
    video_id: str
    relevant: bool
    title_ko: str = ""  # 해외 영상 제목 번역


class RelevanceOut(BaseModel):
    items: list[RelevanceItem]


async def run(ctx: StepContext) -> list[Ref]:
    inp: Input = ctx.read("input")
    if not inp.keywords:
        raise StepInputError("검색어가 없어요. 1단계를 먼저 하거나 검색어를 적어 주세요")

    yt = ctx.adapters.youtube
    now = utcnow()
    since = now - timedelta(days=LOOKBACK_DAYS)
    world = _world_searches(ctx, inp)

    keywords = inp.keywords[: min(MAX_SEARCH_KEYWORDS, MAX_SEARCHES - len(world))]
    if len(inp.keywords) > len(keywords):
        ctx.warn(
            f"YouTube 한도를 지키려고 앞의 검색어 {len(keywords)}개만 찾았어요: "
            f"{', '.join(inp.keywords[len(keywords) :])}은 빠졌어요 "
            "(순서를 바꾸면 찾는 검색어가 바뀌어요)"
        )
    total = len(keywords) + len(world)
    market_of: dict[str, str] = {}  # 영상 ID → 시장 ("" = 입력의 지역)
    used = 0  # 이번 실행의 search.list 횟수 (MAX_SEARCHES = 1회 450 units 한도)
    retried: list[str] = []

    async def find(kw: str, region: str, lang: str, planned_left: int) -> list[str]:
        """조회수 순으로 찾고, 비면 관련도 순으로 한 번 더 (남은 예정 검색까지 한도 안일 때만).

        2026-11-03: '분식점 신메뉴'를 조회수 순 + 최근 180일로 찾으니 totalResults 28만인데
        items가 0개였다(관련도 순은 25개). 좁은 가게 키워드에서 S2가 '검색 결과 없음'으로 멈췄다.
        """
        nonlocal used
        ids = await yt.search(kw, region, lang, since, SEARCH_MAX_RESULTS)
        used += 1
        if not ids and used + planned_left < MAX_SEARCHES:
            try:
                ids = await yt.search(
                    kw, region, lang, since, SEARCH_MAX_RESULTS, order="relevance"
                )
            except QuotaExceeded:  # 다시 찾는 것은 보탬이다: 하루 한도면 다른 키워드 결과로 간다
                return []
            used += 1
            retried.append(kw)
        return ids

    for i, kw in enumerate(keywords):
        await ctx.progress(f"search:{kw}", i / total)
        for vid in await find(kw, inp.region, inp.lang, total - i - 1):
            market_of.setdefault(vid, "")
    charts: list[VideoInfo] = []
    for i, (kw, lang, region) in enumerate(world, start=len(keywords)):
        await ctx.progress(f"search:{kw}", i / total)
        try:  # 해외는 보탬이다: 실패해도 한국 후보로 진행한다
            for vid in await find(kw, region, lang, total - i - 1):
                market_of.setdefault(vid, region)
            for v in await yt.trending(region):
                if v.video_id not in market_of and v.published_at >= since:
                    market_of[v.video_id] = region
                    charts.append(v)
        except QuotaExceeded:
            ctx.warn("오늘 YouTube 한도에 가까워 해외 영상은 찾지 않았어요. 내일은 다시 찾아요")
            break
        except Exception as e:  # noqa: BLE001
            log.warning("market search failed (%s)", region, exc_info=e)
            ctx.warn(f"{region} 영상을 찾지 못해 건너뛰었어요")
    if retried:
        ctx.warn(
            f"'{', '.join(retried)}'은 인기순 결과가 비어서 비슷한 영상 순으로 다시 찾았어요 "
            "(검색어가 좁으면 YouTube가 빈 목록을 줄 때가 있어요)"
        )
    if not market_of:
        raise StepInputError("검색 결과가 없어요. 검색어를 바꿔 보세요", "no_refs")

    chart_ids = {v.video_id for v in charts}
    videos = await yt.videos([v for v in market_of if v not in chart_ids]) + charts
    max_len = ctx.settings.ref_max_duration_sec
    videos = [v for v in videos if 0 < v.duration_sec <= max_len]  # 라이브는 길이가 0이다
    if not videos:
        raise StepInputError(f"{max_len}초 이하 영상을 찾지 못했어요", "no_refs")

    channels = await yt.channels(sorted({v.channel_id for v in videos}))
    subs = {c.channel_id: c.subs for c in channels}

    candidates: list[Ref] = []
    for market in dict.fromkeys(market_of[v.video_id] for v in videos):
        pool = [v for v in videos if market_of[v.video_id] == market]
        refs = build_refs(pool, subs, now)  # 시장 안에서 점수를 낸다
        for r in refs:
            r.market = market
        found = [r for r in refs if r.video_id not in chart_ids]
        chart = [r for r in refs if r.video_id in chart_ids]
        limit = WORLD_CANDIDATES if market else LOCAL_CANDIDATES if world else RELEVANCE_CANDIDATES
        candidates += found[:limit] + chart[:TRENDING_CANDIDATES]
    await _judge_relevance(ctx, inp, candidates, {v.video_id: v for v in videos}, chart_ids)
    # 인기 차트는 주제와 무관한 영상이 대부분이다: 관련 있다고 판정된 것만 남긴다
    candidates = [r for r in candidates if r.video_id not in chart_ids or r.relevant]

    # 관련 있음(또는 판정 없음)을 먼저, 그 안에서는 점수 순 (점수는 시장 안에서만 비교한다)
    candidates.sort(key=lambda r: (r.relevant is False, r.views < MIN_REF_VIEWS, -r.score))
    local = [r for r in candidates if not r.market][: LOCAL_TOP if world else TOP_N]
    overseas = _take_per_market([r for r in candidates if r.market], WORLD_TOP)
    refs = local + overseas
    selectable = [r for r in refs if r.relevant is not False]
    if not selectable:
        # 관련성 높은 후보가 하나도 없어도 멈추지 않는다 — 점수 순으로 고르고 알린다
        selectable = refs
        ctx.warn("주제와 딱 맞는 영상이 없어 인기 순으로 골랐어요. 고른 영상을 한 번 확인해 주세요")
    chosen = _choose(selectable)
    for r in chosen:
        r.selected = True
    wanted = SELECT_LOCAL + SELECT_WORLD
    if world and len(chosen) < wanted:
        ctx.warn(
            f"주제에 맞는 영상이 {len(chosen)}개뿐이라 그것만 골랐어요. 분석 근거가 적을 수 있어요"
        )
    weak = sum(1 for r in chosen if r.views < MIN_REF_VIEWS)
    if weak:
        ctx.warn(
            f"조회수 {MIN_REF_VIEWS:,}회가 안 되는 영상 {weak}개도 골랐어요. 근거가 약할 수 있어요"
        )
    if len(refs) < MIN_REFS:
        ctx.warn(
            f"최근 {LOOKBACK_DAYS}일 · {max_len}초 이하 숏폼이 {len(refs)}개뿐이에요. "
            "검색어를 더 짧고 넓게(2~3단어) 바꾸면 더 찾을 수 있어요"
        )

    hidden = sum(1 for r in refs if r.subs is None)
    if hidden:
        ctx.warn(f"구독자 수를 숨긴 채널의 영상 {hidden}개는 구독자 수 없이 점수를 매겼어요")
    return refs


def _world_searches(ctx: StepContext, inp: Input) -> list[tuple[str, str, str]]:
    """[(검색어, 언어, 지역)]. 입력과 같은 언어의 시장은 뺀다."""
    words = {w.lang: w.keyword for w in inp.world_keywords}
    out = [
        (words[lang], lang, region)
        for lang, region in markets(ctx.settings, inp)
        if lang != inp.lang and lang in words
    ]
    return out[:MAX_WORLD_SEARCHES]


def _take_per_market(refs: list[Ref], n: int) -> list[Ref]:
    out: list[Ref] = []
    for market in dict.fromkeys(r.market for r in refs):
        out += [r for r in refs if r.market == market][:n]
    return out


def _choose(refs: list[Ref]) -> list[Ref]:
    """기본 선택: 한국 3 + 해외 3(시장을 번갈아), 한 채널 2개까지. 모자라면 남은 후보로 채운다."""
    local = [r for r in refs if not r.market]
    overseas = [r for r in refs if r.market]
    # 시장을 번갈아 고르도록 시장 안 순번으로 줄 세운다 (sort는 안정 정렬)
    seen: dict[str, int] = {}
    turns = []
    for r in overseas:
        seen[r.market] = seen.get(r.market, 0) + 1
        turns.append((seen[r.market], len(turns), r))
    overseas = [r for _, _, r in sorted(turns, key=lambda t: t[:2])]

    used: dict[str, int] = {}

    def pick(pool: list[Ref], n: int) -> list[Ref]:
        out: list[Ref] = []
        for r in pool:
            if len(out) == n:
                break
            if used.get(r.channel_id, 0) < MAX_PER_CHANNEL:
                used[r.channel_id] = used.get(r.channel_id, 0) + 1
                out.append(r)
        return out

    if overseas:
        total = SELECT_LOCAL + SELECT_WORLD
        chosen = pick(local, SELECT_LOCAL) + pick(overseas, SELECT_WORLD)
    else:
        total = DEFAULT_SELECTED
        chosen = pick(local, total)
    # 채널 상한 때문에 모자라면 상한 없이 채운다 (분석 근거가 줄어드는 쪽이 더 나쁘다)
    rest = [r for r in refs if r not in chosen]
    return chosen + rest[: total - len(chosen)]


async def _judge_relevance(
    ctx: StepContext,
    inp: Input,
    refs: list[Ref],
    videos: dict[str, VideoInfo],
    chart_ids: set[str],
) -> None:
    """refs[].relevant를 채운다. 실패하면 경고만 남기고 점수 순서를 그대로 쓴다."""
    lines = []
    for r in refs:
        tags = ", ".join(videos[r.video_id].tags[:TAGS_IN_PROMPT])
        lines.append(
            f"video_id: {r.video_id}\n"
            + (f"market: {r.market}\n" if r.market else "")
            + f"title: {wrap_untrusted(r.title)}\n"
            f"tags: {wrap_untrusted(tags)}"
        )
    user = (
        f"topic: {inp.topic}\naudience: {inp.audience}\nkeywords: {', '.join(inp.keywords)}\n\n"
        + "\n\n".join(lines)
    )
    try:
        out = await ctx.adapters.llm.generate_json(
            "s2_relevance", load_prompt("s2_relevance").text, user, RelevanceOut
        )
    except Exception:  # 관련성 판정은 보조 기능 — S2 전체를 실패시키지 않는다
        ctx.warn("주제 관련성을 확인하지 못해 인기 순으로만 골랐어요")
        return
    verdict = {it.video_id: it for it in out.items}
    for r in refs:
        item = verdict.get(r.video_id)
        r.relevant = item.relevant if item else None
        if item and r.market and item.title_ko.strip():
            r.title_ko = item.title_ko.strip()[:200]
