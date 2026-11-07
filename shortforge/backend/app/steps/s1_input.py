"""S1 개인 입력: 입력 정규화 + 검색 키워드 3개 (F-1.1, F-1.2). 사용자는 5개까지 고칠 수 있다."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.llm import load_prompt
from app.modes import business_block, listing_keywords, markets, shop_keywords
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Input, WorldKeyword

MAX_AUTO_KEYWORDS = 3  # = s2_search.MAX_SEARCH_KEYWORDS (단계끼리 import하지 않는다)
MAX_KEYWORDS_WITH_WORLD = 2  # 해외 시장이 있으면 합쳐서 4번만 검색한다


class WorldDraft(BaseModel):
    lang: str
    keyword: str = ""  # 빈 값은 버린다 (해외는 보탬이라 이것 때문에 S1이 실패하면 안 된다)


class KeywordsOut(BaseModel):
    keywords: list[str] = Field(min_length=3, max_length=5)
    world: list[WorldDraft] = Field(default_factory=list)  # 해외 시장마다 하나


async def run(ctx: StepContext) -> Input:
    inp: Input | None = ctx.current()
    if inp is None:
        raise StepInputError("주제를 먼저 적어 주세요")

    inp.topic = " ".join(inp.topic.split())
    inp.audience = " ".join(inp.audience.split())

    # 사용자가 고친 키워드는 그대로 둔다. 자동 키워드가 예전 주제로 만든 것이면 다시 만든다
    if (
        inp.keywords
        and inp.keywords_topic
        and inp.keywords_topic != inp.topic
        and inp.keywords == inp.keywords_auto
    ):
        inp.keywords = []
    langs = [lang for lang, _ in markets(ctx.settings, inp) if lang != inp.lang]
    need_world = bool(langs) and (not inp.world_keywords or inp.world_topic != inp.topic)
    if not inp.keywords or need_world:
        prompt = load_prompt("s1_keywords")
        user = (
            f"topic: {inp.topic}\naudience: {inp.audience}\ntone: {inp.tone}\n"
            f"duration_sec: {inp.duration_sec}\nlang: {inp.lang}\nregion: {inp.region}\n"
            f"world_langs: {', '.join(langs)}{business_block(inp)}"
            + (
                "\n\n[검색어] 가게 이름·동네만으로 된 검색어는 만들지 않는다. "
                "메뉴·업종 중심의 넓은 말로 쓴다 (예: 떡볶이 신메뉴, 분식집 홍보)"
                if inp.mode == "business"
                else "\n\n[검색어] 단지·사무소 이름으로 된 검색어는 만들지 않는다. "
                "매물 종류·거래 형태 중심의 넓은 말로 쓴다 "
                "(예: 아파트 전세 매물, 오피스텔 랜선 집들이)"
                if inp.mode == "listing"
                else ""
            )
            + (
                f"\n\n[결과가 없던 검색어] {', '.join(inp.keywords_failed)} — "
                "이것들과 다른, 더 넓고 흔한 검색어로 쓴다"
                if inp.keywords_failed
                else ""
            )
        )
        try:
            out = await ctx.adapters.llm.generate_json(
                "s1_keywords", prompt.text, user, KeywordsOut
            )
        except Exception:
            if not inp.keywords:
                raise
            # 키워드가 이미 있으면 해외 검색어 때문에 멈추지 않는다
            ctx.warn("해외 검색어를 만들지 못해 이번에는 한국 검색어로만 찾아요")
            return inp
        # S2는 쿼터 때문에 앞의 일부만 검색한다. 더 만들면 매번 '제외했다' 경고만 남는다
        limit = MAX_KEYWORDS_WITH_WORLD if langs else MAX_AUTO_KEYWORDS
        if not inp.keywords:
            failed = {k.lower() for k in inp.keywords_failed}
            made = [k for k in _dedupe(out.keywords) if k.lower() not in failed] or _dedupe(
                out.keywords
            )
            if inp.mode == "business" and inp.business:
                made = shop_keywords(made, inp.business)
            if inp.mode == "listing" and inp.listing:
                made = listing_keywords(made, inp.listing)
            inp.keywords = made[:limit]
            inp.keywords_auto = list(inp.keywords)
            inp.keywords_topic = inp.topic
        wanted = {w.lang.lower(): w.keyword.strip() for w in reversed(out.world)}
        inp.world_keywords = [
            WorldKeyword(lang=lang, keyword=wanted[lang]) for lang in langs if wanted.get(lang)
        ]
        inp.world_topic = inp.topic
    return inp


def _dedupe(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for k in (" ".join(k.split()) for k in keywords):
        if k and k.lower() not in seen:
            seen.add(k.lower())
            result.append(k)
    return result[:5]
