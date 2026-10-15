"""S1 개인 입력: 입력 정규화 + 검색 키워드 3~5개 (F-1.1, F-1.2)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.llm import load_prompt
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Input


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
        inp.keywords = _dedupe(out.keywords)
    return inp


def _dedupe(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for k in (" ".join(k.split()) for k in keywords):
        if k and k.lower() not in seen:
            seen.add(k.lower())
            result.append(k)
    return result[:5]
