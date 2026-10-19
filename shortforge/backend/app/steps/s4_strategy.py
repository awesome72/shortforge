"""S4 제작 전략: 장면 스토리보드 + 제목 A/B (F-4.1, F-4.2).

LLM 결과를 검토해 문제가 있으면 [수정 요청]을 붙여 다시 생성한다 (최대 MAX_ATTEMPTS회).
- 치명: 첫 장면이 0~2초 hook이 아님, 제목이 레퍼런스 제목과 너무 비슷함(Jaccard > 0.6)
  → 끝까지 못 고치면 실패
- 교정: 전체 길이가 목표 ±15% 밖 → 끝까지 못 고치면 경고만 남긴다
- 참고: 장면 길이 2~8초 밖, 분석에 없는 요인 참조, 장면 시간 불연속 → 경고
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.llm import load_prompt, wrap_untrusted
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Factor, Input, Ref, Scene, Strategy

MAX_ATTEMPTS = 3
HOOK_MAX_END = 2.0
SCENE_MIN, SCENE_MAX = 2.0, 8.0
DURATION_TOLERANCE = 0.15
TITLE_JACCARD_MAX = 0.6
CHARS_PER_SEC = 6.0  # Edge-TTS 한국어 +0% 실측 (공백·문장부호 포함)
HOOK_SLACK_CHARS = 4
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
    names = {f.name for f in factors}
    base += f"\n\nfactor_refs에 쓸 수 있는 이름: {', '.join(sorted(names))}"
    prompt = load_prompt("s4_strategy")

    feedback: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        user = base
        if feedback:
            user += "\n\n[수정 요청]\n" + "\n".join(f"- {x}" for x in feedback)
        strategy = await ctx.adapters.llm.generate_json("s4_strategy", prompt.text, user, Strategy)
        fatal, fixable, notes = review(strategy, inp.duration_sec, names, [r.title for r in refs])
        limits = line_limits(strategy, inp.duration_sec)
        length_only = set(fixable) <= set(length_messages(strategy, inp.duration_sec))
        if not fatal and fixable and length_only:
            # 대사 길이만 문제면 전략 전체(주 모델, 8~30초)를 다시 만들지 않고
            # 그 대사만 경량 모델로 줄인다(1~2초). 주 모델은 다시 만들 때 글자 수를 잘 못 맞춘다
            shorter = await shorten_lines(ctx, strategy, limits, inp.topic)
            if shorter is not None:
                strategy = shorter
                fatal, fixable, notes = review(
                    strategy, inp.duration_sec, names, [r.title for r in refs]
                )
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

    # 대사 분량: 계획한 시간은 TTS가 실제로 읽는 길이와 맞아야 한다 (실측 약 6자/초)
    fixable += length_messages(strategy, duration_sec)

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


# ── 대사 길이 ───────────────────────────────────────────


def _hook_limit(first: Scene) -> int:
    return round((first.end - first.start) * CHARS_PER_SEC) + HOOK_SLACK_CHARS


def _total_over(strategy: Strategy, duration_sec: int) -> tuple[int, int] | None:
    """(대사 총 글자 수, 권장 글자 수). 권장보다 15% 넘게 길 때만."""
    chars = sum(len(s.line.strip()) for s in strategy.scenes)
    budget = round(duration_sec * CHARS_PER_SEC)
    return (chars, budget) if chars > budget * (1 + DURATION_TOLERANCE) else None


def line_limits(strategy: Strategy, duration_sec: int) -> dict[str, int]:
    """줄여야 하는 장면과 그 대사의 최대 글자 수.

    - 훅: 장면 길이 × 6자/초 + 여유 4자
    - 대사 총량이 길면: 장면 길이 × 6자/초를 넘는 장면 모두 (합치면 권장 총량 안에 든다)
    """
    first = strategy.scenes[0]
    limits: dict[str, int] = {}
    if len(first.line.strip()) > _hook_limit(first):
        limits[first.id] = _hook_limit(first)
    if _total_over(strategy, duration_sec):
        for s in strategy.scenes:
            limit = max(4, round((s.end - s.start) * CHARS_PER_SEC))
            if len(s.line.strip()) > limit:
                limits[s.id] = min(limits.get(s.id, limit), limit)
    return limits


def length_messages(strategy: Strategy, duration_sec: int) -> list[str]:
    """대사 길이 교정 요청. 다시 만들 때 모델이 지금 대사를 보고 고칠 수 있게 대사를 함께 적는다."""
    out: list[str] = []
    first = strategy.scenes[0]
    if len(first.line.strip()) > _hook_limit(first):
        n = len(first.line.strip())
        out.append(f"훅 대사 '{first.line.strip()}'({n}자)를 {_hook_limit(first)}자 이내로 줄인다")
    over = _total_over(strategy, duration_sec)
    if over:
        chars, budget = over
        out.append(
            f"대사가 총 {chars}자로 {duration_sec}초에 비해 길다 — {budget}자 안팎으로 줄인다 "
            f"(한국어 낭독 약 {CHARS_PER_SEC:g}자/초)"
        )
    return out


class ShortLine(BaseModel):
    id: str
    line: str


class ShortenOut(BaseModel):
    scenes: list[ShortLine]


async def shorten_lines(
    ctx: StepContext, strategy: Strategy, limits: dict[str, int], topic: str
) -> Strategy | None:
    """긴 대사만 경량 LLM 1회로 줄인 전략. 실패하면 None (그때는 전략 전체를 다시 만든다)."""
    if not limits:
        return None
    lines = [
        f"{s.id} role={s.role} "
        + (f"max_chars={limits[s.id]} (지금 {len(s.line.strip())}자) " if s.id in limits else "")
        + f"line={s.line.strip()!r}"
        for s in strategy.scenes
    ]
    user = f"topic: {topic}\n줄일 장면: {', '.join(limits)}\n\n" + "\n".join(lines)
    try:
        out = await ctx.adapters.llm.generate_json(
            "s4_shorten", load_prompt("s4_shorten").text, user, ShortenOut
        )
    except Exception:  # noqa: BLE001 - 줄이기는 보조 수단이다. 실패하면 다시 만든다
        return None
    new = {x.id: x.line.strip() for x in out.scenes if x.id in limits and x.line.strip()}
    if not new:
        return None
    scenes = [s.model_copy(update={"line": new.get(s.id, s.line)}) for s in strategy.scenes]
    return strategy.model_copy(update={"scenes": scenes})
