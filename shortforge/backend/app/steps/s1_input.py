"""S1 개인 입력: 입력 정규화 + 검색 키워드 3개 (F-1.1, F-1.2). 사용자는 5개까지 고칠 수 있다."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.llm import load_prompt
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
        raise StepInputError("주제를 먼저 입력해야 한다")

    inp.topic = " ".join(inp.topic.split())
    inp.audience = " ".join(inp.audience.split())

    # 사용자가 이미 편집한 키워드가 있으면 그대로 둔다
    langs = [lang for lang, _ in ctx.settings.markets if lang != inp.lang]
    need_world = bool(langs) and (not inp.world_keywords or inp.world_topic != inp.topic)
    if not inp.keywords or need_world:
        prompt = load_prompt("s1_keywords")
        user = (
            f"topic: {inp.topic}\naudience: {inp.audience}\ntone: {inp.tone}\n"
            f"duration_sec: {inp.duration_sec}\nlang: {inp.lang}\nregion: {inp.region}\n"
            f"world_langs: {', '.join(langs)}"
        )
        try:
            out = await ctx.adapters.llm.generate_json(
                "s1_keywords", prompt.text, user, KeywordsOut
            )
        except Exception:
            if not inp.keywords:
                raise
            # 키워드가 이미 있으면 해외 검색어 때문에 멈추지 않는다
            ctx.warn("해외 검색어를 만들지 못해 이번에는 입력한 키워드로만 찾는다")
            return inp
        # S2는 쿼터 때문에 앞의 일부만 검색한다. 더 만들면 매번 '제외했다' 경고만 남는다
        limit = MAX_KEYWORDS_WITH_WORLD if langs else MAX_AUTO_KEYWORDS
        inp.keywords = inp.keywords or _dedupe(out.keywords)[:limit]
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
