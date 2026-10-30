"""S2 레퍼런스 탐색: 구독자 대비 상위 숏폼 (F-2.1~F-2.4). 한국과 해외 시장을 함께 찾는다.

순서: 시장별 search(+해외 인기 차트) → videos/channels 일괄 조회 → 길이 필터
→ 시장 안에서 점수 → LLM 관련성 판정·제목 번역 → 시장을 섞어 선택.
조회수 규모가 나라마다 달라 점수는 시장마다 따로 낸다.
캐시(24h)와 쿼터는 YouTube 어댑터가 맡는다.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel

from app.adapters.base import VideoInfo
from app.llm import load_prompt, wrap_untrusted
from app.orchestrator import StepContext, StepInputError
from app.quota import QuotaExceeded
from app.schemas.project import Input, Ref, utcnow
from app.scoring import build_refs

LOOKBACK_DAYS = 90
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
        raise StepInputError("검색 키워드가 없다 — S1을 먼저 실행하거나 키워드를 입력한다")

    yt = ctx.adapters.youtube
    now = utcnow()
    since = now - timedelta(days=LOOKBACK_DAYS)
    world = _world_searches(ctx, inp)

    keywords = inp.keywords[: min(MAX_SEARCH_KEYWORDS, MAX_SEARCHES - len(world))]
    if len(inp.keywords) > len(keywords):
        ctx.warn(
            f"쿼터(1회 ≤ 450 units)를 지키려고 앞의 키워드 {len(keywords)}개만 검색했다: "
            f"{', '.join(inp.keywords[len(keywords) :])} 제외 — 순서를 바꾸면 대상이 바뀐다"
        )
    total = len(keywords) + len(world)
    market_of: dict[str, str] = {}  # 영상 ID → 시장 ("" = 입력의 지역)
    for i, kw in enumerate(keywords):
        await ctx.progress(f"search:{kw}", i / total)
        for vid in await yt.search(kw, inp.region, inp.lang, since, SEARCH_MAX_RESULTS):
            market_of.setdefault(vid, "")
    charts: list[VideoInfo] = []
    for i, (kw, lang, region) in enumerate(world, start=len(keywords)):
        await ctx.progress(f"search:{kw}", i / total)
        try:  # 해외는 보탬이다: 실패해도 한국 후보로 진행한다
            for vid in await yt.search(kw, region, lang, since, SEARCH_MAX_RESULTS):
                market_of.setdefault(vid, region)
            for v in await yt.trending(region):
                if v.video_id not in market_of and v.published_at >= since:
                    market_of[v.video_id] = region
                    charts.append(v)
        except QuotaExceeded:
            ctx.warn("오늘 YouTube 한도에 가까워 해외 영상은 찾지 않았어요. 내일은 다시 찾아요")
            break
        except Exception as e:  # noqa: BLE001
            ctx.warn(f"{region} 영상을 찾지 못해 건너뛰었다 ({type(e).__name__})")
    if not market_of:
        raise StepInputError("검색 결과가 없다 — 키워드를 바꿔 본다")

    chart_ids = {v.video_id for v in charts}
    videos = await yt.videos([v for v in market_of if v not in chart_ids]) + charts
    max_len = ctx.settings.ref_max_duration_sec
    videos = [v for v in videos if 0 < v.duration_sec <= max_len]  # 라이브는 길이가 0이다
    if not videos:
        raise StepInputError(f"{max_len}초 이하 영상이 없다")

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
        ctx.warn("주제와 관련성이 높은 후보가 없어 점수 순으로 골랐다 — 선택을 확인한다")
    chosen = _choose(selectable)
    for r in chosen:
        r.selected = True
    wanted = SELECT_LOCAL + SELECT_WORLD
    if world and len(chosen) < wanted:
        ctx.warn(
            f"주제에 맞는 영상이 {len(chosen)}개뿐이라 그것만 골랐다 — 분석 근거가 적을 수 있다"
        )
    weak = sum(1 for r in chosen if r.views < MIN_REF_VIEWS)
    if weak:
        ctx.warn(f"조회수 {MIN_REF_VIEWS:,}회 미만 영상 {weak}개까지 골랐다 — 근거가 약할 수 있다")
    if len(refs) < MIN_REFS:
        ctx.warn(
            f"조건(최근 {LOOKBACK_DAYS}일 · {max_len}초 이하)에 맞는 숏폼이 {len(refs)}개뿐이다 — "
            "1단계에서 키워드를 더 짧고 넓게(2~3단어) 바꿔 다시 검색한다"
        )

    hidden = sum(1 for r in refs if r.subs is None)
    if hidden:
        ctx.warn(f"구독자 수를 숨긴 채널의 영상 {hidden}개는 구독자 대비 배수 없이 점수를 매겼다")
    return refs


def _world_searches(ctx: StepContext, inp: Input) -> list[tuple[str, str, str]]:
    """[(검색어, 언어, 지역)]. 입력과 같은 언어의 시장은 뺀다."""
    words = {w.lang: w.keyword for w in inp.world_keywords}
    out = [
        (words[lang], lang, region)
        for lang, region in ctx.settings.markets
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
    except Exception as e:  # 관련성 판정은 보조 기능 — S2 전체를 실패시키지 않는다
        ctx.warn(f"관련성 판정을 건너뛰었다 ({type(e).__name__}) — 점수 순으로만 골랐다")
        return
    verdict = {it.video_id: it for it in out.items}
    for r in refs:
        item = verdict.get(r.video_id)
        r.relevant = item.relevant if item else None
        if item and r.market and item.title_ko.strip():
            r.title_ko = item.title_ko.strip()[:200]
    off = sum(1 for r in refs if r.relevant is False and r.video_id not in chart_ids)
    if off:
        ctx.warn(f"주제와 관련이 낮은 후보 {off}개를 뒤로 보내고 기본 선택에서 뺐다")
