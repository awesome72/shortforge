"""S4 제작 전략: 장면 스토리보드 + 제목 A/B (F-4.1, F-4.2).

LLM 재시도와 제목 유사도(Jaccard) 검사는 Step 4에서 붙인다.
"""

from __future__ import annotations

from app.llm import load_prompt
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Factor, Input, Strategy

HOOK_MAX_END = 2.0
SCENE_MIN, SCENE_MAX = 2.0, 8.0
DURATION_TOLERANCE = 0.15


async def run(ctx: StepContext) -> Strategy:
    inp: Input = ctx.read("input")
    factors: list[Factor] = ctx.read("factors")

    factor_lines = "\n".join(f"- {f.name} ({f.confidence}): {f.finding}" for f in factors)
    user = (
        f"topic: {inp.topic}\naudience: {inp.audience}\ntone: {inp.tone}\n"
        f"duration_sec: {inp.duration_sec}\nlang: {inp.lang}\n\nfactors:\n{factor_lines}"
    )
    prompt = load_prompt("s4_strategy")
    strategy = await ctx.adapters.llm.generate_json("s4_strategy", prompt.text, user, Strategy)
    check_strategy(ctx, strategy, inp.duration_sec, {f.name for f in factors})
    return strategy


def check_strategy(
    ctx: StepContext, strategy: Strategy, duration_sec: int, factor_names: set[str]
) -> None:
    scenes = strategy.scenes
    first = scenes[0]
    if first.role != "hook" or first.start != 0 or first.end > HOOK_MAX_END:
        raise StepInputError("첫 장면은 0~2초의 hook이어야 한다")

    for s in scenes:
        length = s.end - s.start
        if not SCENE_MIN <= length <= SCENE_MAX and s is not first:
            ctx.warn(f"{s.id} 길이 {length:.1f}초가 권장 범위(2~8초)를 벗어난다")
        unknown = set(s.factor_refs) - factor_names
        if unknown:
            ctx.warn(f"{s.id}가 분석에 없는 요인을 참조한다: {', '.join(sorted(unknown))}")

    total = scenes[-1].end
    if abs(total - duration_sec) > duration_sec * DURATION_TOLERANCE:
        ctx.warn(f"전체 길이 {total:.1f}초가 목표 {duration_sec}초의 ±15%를 벗어난다")
