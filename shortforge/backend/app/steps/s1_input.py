"""S1 개인 입력: 입력 정규화 + 검색 키워드 3개 (F-1.1, F-1.2). 사용자는 5개까지 고칠 수 있다."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.llm import load_prompt
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Input

MAX_AUTO_KEYWORDS = 3  # = s2_search.MAX_SEARCH_KEYWORDS (단계끼리 import하지 않는다)


class KeywordsOut(BaseModel):
    keywords: list[str] = Field(min_length=3, max_length=5)


async def run(ctx: StepContext) -> Input:
    inp: Input | None = ctx.current()
    if inp is None:
        raise StepInputError("주제를 먼저 입력해야 한다")

    inp.topic = " ".join(inp.topic.split())
    inp.audience = " ".join(inp.audience.split())

    # 사용자가 이미 편집한 키워드가 있으면 그대로 둔다
    if not inp.keywords:
        prompt = load_prompt("s1_keywords")
        user = (
            f"topic: {inp.topic}\naudience: {inp.audience}\ntone: {inp.tone}\n"
            f"duration_sec: {inp.duration_sec}\nlang: {inp.lang}\nregion: {inp.region}"
        )
        out = await ctx.adapters.llm.generate_json("s1_keywords", prompt.text, user, KeywordsOut)
        # S2는 쿼터 때문에 앞의 3개만 검색한다. 더 만들면 매번 '제외했다' 경고만 남는다
        inp.keywords = _dedupe(out.keywords)[:MAX_AUTO_KEYWORDS]
    return inp


def _dedupe(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for k in (" ".join(k.split()) for k in keywords):
        if k and k.lower() not in seen:
            seen.add(k.lower())
            result.append(k)
    return result[:5]
