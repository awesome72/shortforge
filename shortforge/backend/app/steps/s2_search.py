"""S2 레퍼런스 탐색: 구독자 대비 상위 숏폼 (F-2.1~F-2.4).

순서: 키워드별 search → videos/channels 일괄 조회 → 길이 필터 → 점수 → LLM 관련성 판정 → 상위 10.
캐시(24h)와 쿼터는 YouTube 어댑터가 맡는다.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel

from app.adapters.base import VideoInfo
from app.llm import load_prompt, wrap_untrusted
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Input, Ref, utcnow
from app.scoring import build_refs

LOOKBACK_DAYS = 90
SEARCH_MAX_RESULTS = 25
# search.list는 100 units. 4번이면 videos/channels를 더해 400을 넘는다 (DoD: S2 1회 ≤ 400 units)
MAX_SEARCH_KEYWORDS = 3
RELEVANCE_CANDIDATES = 20  # 점수 상위 몇 개를 관련성 판정에 넘길지
TOP_N = 10
DEFAULT_SELECTED = 4
MIN_REFS = 4  # 이보다 적으면 분석 근거가 빈약하다
TAGS_IN_PROMPT = 8


class RelevanceItem(BaseModel):
    video_id: str
    relevant: bool


class RelevanceOut(BaseModel):
    items: list[RelevanceItem]


async def run(ctx: StepContext) -> list[Ref]:
    inp: Input = ctx.read("input")
    if not inp.keywords:
        raise StepInputError("검색 키워드가 없다 — S1을 먼저 실행하거나 키워드를 입력한다")

    yt = ctx.adapters.youtube
    now = utcnow()
    since = now - timedelta(days=LOOKBACK_DAYS)

    keywords = inp.keywords[:MAX_SEARCH_KEYWORDS]
    if len(inp.keywords) > MAX_SEARCH_KEYWORDS:
        ctx.warn(
            f"쿼터(1회 ≤ 400 units)를 지키려고 앞의 키워드 {MAX_SEARCH_KEYWORDS}개만 검색했다: "
            f"{', '.join(inp.keywords[MAX_SEARCH_KEYWORDS:])} 제외 — 순서를 바꾸면 대상이 바뀐다"
        )
    ids: list[str] = []
    for i, kw in enumerate(keywords):
        await ctx.progress(f"search:{kw}", i / len(keywords))
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

    candidates = build_refs(videos, subs, now)[:RELEVANCE_CANDIDATES]
    await _judge_relevance(ctx, inp, candidates, {v.video_id: v for v in videos})

    # 관련 있음(또는 판정 없음)을 먼저, 그 안에서는 점수 순 (sort는 안정 정렬)
    candidates.sort(key=lambda r: r.relevant is False)
    refs = candidates[:TOP_N]
    selectable = [r for r in refs if r.relevant is not False]
    if not selectable:
        # 관련성 높은 후보가 하나도 없어도 멈추지 않는다 — 점수 순으로 고르고 알린다
        selectable = refs
        ctx.warn("주제와 관련성이 높은 후보가 없어 점수 순으로 골랐다 — 선택을 확인한다")
    for r in selectable[:DEFAULT_SELECTED]:
        r.selected = True
    if len(refs) < MIN_REFS:
        ctx.warn(
            f"조건(최근 {LOOKBACK_DAYS}일 · {max_len}초 이하)에 맞는 숏폼이 {len(refs)}개뿐이다 — "
            "1단계에서 키워드를 더 짧고 넓게(2~3단어) 바꿔 다시 검색한다"
        )

    hidden = sum(1 for r in refs if r.subs is None)
    if hidden:
        ctx.warn(f"구독자 수를 숨긴 채널의 영상 {hidden}개는 구독자 대비 배수 없이 점수를 매겼다")
    return refs


async def _judge_relevance(
    ctx: StepContext, inp: Input, refs: list[Ref], videos: dict[str, VideoInfo]
) -> None:
    """refs[].relevant를 채운다. 실패하면 경고만 남기고 점수 순서를 그대로 쓴다."""
    lines = []
    for r in refs:
        tags = ", ".join(videos[r.video_id].tags[:TAGS_IN_PROMPT])
        lines.append(
            f"video_id: {r.video_id}\n"
            f"title: {wrap_untrusted(r.title)}\n"
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
    verdict = {it.video_id: it.relevant for it in out.items}
    for r in refs:
        r.relevant = verdict.get(r.video_id)
    off = sum(1 for r in refs if r.relevant is False)
    if off:
        ctx.warn(f"주제와 관련이 낮은 후보 {off}개를 뒤로 보내고 기본 선택에서 뺐다")
