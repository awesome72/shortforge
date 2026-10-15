"""S4 제작 전략: 장면 스토리보드 + 제목 A/B (F-4.1, F-4.2).

LLM 결과를 검토해 문제가 있으면 [수정 요청]을 붙여 다시 생성한다 (최대 MAX_ATTEMPTS회).
- 치명: 첫 장면이 0~2초 hook이 아님, 제목이 레퍼런스 제목과 너무 비슷함(Jaccard > 0.6)
  → 끝까지 못 고치면 실패
- 교정: 전체 길이가 목표 ±15% 밖 → 끝까지 못 고치면 경고만 남긴다
- 참고: 장면 길이 2~8초 밖, 분석에 없는 요인 참조, 장면 시간 불연속 → 경고
"""

from __future__ import annotations

import re

from app.llm import load_prompt, wrap_untrusted
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Factor, Input, Ref, Strategy

MAX_ATTEMPTS = 3
HOOK_MAX_END = 2.0
SCENE_MIN, SCENE_MAX = 2.0, 8.0
DURATION_TOLERANCE = 0.15
TITLE_JACCARD_MAX = 0.6
STOP_TOKENS = {"shorts", "short", "쇼츠", "숏츠"}


def title_tokens(title: str) -> set[str]:
    return {t for t in re.findall(r"\w+", title.lower()) if t not in STOP_TOKENS}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


async def run(ctx: StepContext) -> Strategy:
    inp: Input = ctx.read("input")
    factors: list[Factor] = ctx.read("factors")
    refs: list[Ref] = [r for r in ctx.read("refs") if r.selected]

    factor_lines = "\n".join(f"- {f.name} ({f.confidence}): {f.finding}" for f in factors)
    ref_titles = "\n".join(f"- {wrap_untrusted(r.title)}" for r in refs)
    base = (
        f"topic: {inp.topic}\naudience: {inp.audience}\ntone: {inp.tone}\n"
        f"duration_sec: {inp.duration_sec}\nlang: {inp.lang}\n\nfactors:\n{factor_lines}\n\n"
        f"reference_titles (구조만 참고, 복사 금지):\n{ref_titles}"
    )
    prompt = load_prompt("s4_strategy")
    names = {f.name for f in factors}

    feedback: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        user = base
        if feedback:
            user += "\n\n[수정 요청]\n" + "\n".join(f"- {x}" for x in feedback)
        strategy = await ctx.adapters.llm.generate_json("s4_strategy", prompt.text, user, Strategy)
        fatal, fixable, notes = review(strategy, inp.duration_sec, names, [r.title for r in refs])
        if not fatal and not fixable:
            break
        feedback = fatal + fixable
        if attempt == MAX_ATTEMPTS:
            if fatal:
                raise StepInputError(
                    f"전략을 {MAX_ATTEMPTS}회 만들었지만 고치지 못했다: " + "; ".join(fatal)
                )
            notes = fixable + notes
    for n in notes:
        ctx.warn(n)
    return strategy


def review(
    strategy: Strategy, duration_sec: int, factor_names: set[str], ref_titles: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """(치명, 교정, 참고) 문제 목록."""
    fatal: list[str] = []
    fixable: list[str] = []
    notes: list[str] = []
    scenes = strategy.scenes

    first = scenes[0]
    if first.role != "hook" or first.start != 0 or first.end > HOOK_MAX_END:
        fatal.append(f"첫 장면은 start=0, end≤{HOOK_MAX_END:g}인 role=hook이어야 한다")

    ref_tokens = [(t, title_tokens(t)) for t in ref_titles]
    for title in strategy.titles:
        mine = title_tokens(title)
        for ref, toks in ref_tokens:
            if jaccard(mine, toks) > TITLE_JACCARD_MAX:
                fatal.append(
                    f"제목 '{title}'이 레퍼런스 제목 '{ref}'와 너무 비슷하다 — 다르게 쓴다"
                )
                break

    total = scenes[-1].end
    if abs(total - duration_sec) > duration_sec * DURATION_TOLERANCE:
        fixable.append(f"전체 길이 {total:g}초를 목표 {duration_sec}초(±15%)에 맞춘다")

    for prev, cur in zip(scenes, scenes[1:], strict=False):
        if abs(cur.start - prev.end) > 0.05:
            notes.append(f"{prev.id}→{cur.id} 시간이 이어지지 않는다 ({prev.end:g}→{cur.start:g})")
    for s in scenes[1:]:
        length = s.end - s.start
        if not SCENE_MIN <= length <= SCENE_MAX:
            notes.append(f"{s.id} 길이 {length:.1f}초가 권장 범위(2~8초)를 벗어난다")
    for s in scenes:
        unknown = set(s.factor_refs) - factor_names
        if unknown:
            notes.append(f"{s.id}가 분석에 없는 요인을 참조한다: {', '.join(sorted(unknown))}")
    return fatal, fixable, notes
