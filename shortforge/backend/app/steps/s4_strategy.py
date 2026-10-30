"""S4 제작 전략: 장면 스토리보드 + 제목 A/B (F-4.1, F-4.2).

LLM 결과를 검토해 문제가 있으면 [수정 요청]을 붙여 다시 생성한다 (최대 MAX_ATTEMPTS회).
- 치명: 첫 장면이 0~2초 hook이 아님, 제목이 레퍼런스 제목과 너무 비슷함(Jaccard > 0.6)
  → 끝까지 못 고치면 실패
- 교정: 전체 길이가 목표 ±15% 밖 → 끝까지 못 고치면 경고만 남긴다
- 참고: 장면 길이 2~8초 밖, 장면 시간 불연속 → 경고 (분석에 없는 요인 참조는 조용히 뺀다)
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.llm import load_prompt, wrap_untrusted
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import (
    LAST_SCENE_EXTRA_PAD,
    Factor,
    Input,
    Ref,
    Scene,
    Strategy,
    TimelineScene,
)

MAX_ATTEMPTS = 3
HOOK_MAX_END = 2.0
SCENE_MIN, SCENE_MAX = 2.0, 8.0
DURATION_TOLERANCE = 0.15
TITLE_JACCARD_MAX = 0.6
# Edge-TTS 한국어 +0% 실측 (공백·문장부호 포함). 6.0은 끝의 조용한 부분까지 센 값이었다.
# 장면 길이를 말 길이(마지막 어절 + 0.25초)로 잡은 뒤로는 6.8 (2026-10-29, 39장면)
CHARS_PER_SEC = 6.8
# 장면마다 S6가 끝에 붙이는 여백. 영상 길이 = 말 + 여백이라 대사 분량은 여백을 빼고 잡는다
# (2026-10 실측: 30초 목표에 186자 → 말 32.2초 + 여백 1.2초 = 33.4초, +11%)
SCENE_PAD = TimelineScene.model_fields["pad"].default
HOOK_SLACK_CHARS = 4
SCOPE_TAG = re.compile(r"\[(?:shared|overseas|local)\]\s*")
STOP_TOKENS = {"shorts", "short", "쇼츠", "숏츠"}


def title_tokens(title: str) -> set[str]:
    return {t for t in re.findall(r"\w+", title.lower()) if t not in STOP_TOKENS}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


async def run(ctx: StepContext) -> Strategy:
    inp: Input = ctx.read("input")
    factors: list[Factor] = ctx.read("factors")
    refs: list[Ref] = [r for r in ctx.read("refs") if r.selected]

    factor_lines = "\n".join(factor_line(f) for f in factors)
    ref_titles = "\n".join(
        f"- {f'[{r.market}] ' if r.market else ''}{wrap_untrusted(r.title)}" for r in refs
    )
    # 해외 제목은 한국어 번역과도 비교한다. 단어 비교라 번역한 베끼기는 원문으로 잡히지 않는다
    compared = [t for r in refs for t in (r.title, r.title_ko) if t]
    if any(r.market and not r.title_ko for r in refs):
        ctx.warn("번역이 없는 해외 제목이 있어 그 제목은 원문과만 비교했다")
    base = (
        f"topic: {inp.topic}\naudience: {inp.audience}\ntone: {inp.tone}\n"
        f"duration_sec: {inp.duration_sec}\nlang: {inp.lang}\n\nfactors:\n{factor_lines}\n\n"
        f"reference_titles (구조만 참고, 복사 금지):\n{ref_titles}"
    )
    names = {f.name for f in factors}
    base += f"\n\nfactor_refs에 쓸 수 있는 이름: {', '.join(sorted(names))}"
    prompt = load_prompt("s4_strategy")

    feedback: list[str] = []
    # 주 모델을 다시 부른 이유(종류만). 10번 중 9번이 2회 호출이라 원인을 찾으려고 남긴다
    retries: list[str] = []
    ctx.stats["s4_retry"] = retries
    for attempt in range(1, MAX_ATTEMPTS + 1):
        user = base
        if feedback:
            user += "\n\n[수정 요청]\n" + "\n".join(f"- {x}" for x in feedback)
        strategy = await ctx.adapters.llm.generate_json("s4_strategy", prompt.text, user, Strategy)
        strategy = drop_unknown_refs(strategy, names)
        fatal, fixable, notes = review(strategy, inp.duration_sec, names, compared)
        limits = line_limits(strategy, inp.duration_sec)
        length_only = set(fixable) <= set(length_messages(strategy, inp.duration_sec))
        if not fatal and fixable and length_only:
            # 대사 길이만 문제면 전략 전체(주 모델, 8~30초)를 다시 만들지 않고
            # 그 대사만 경량 모델로 줄인다(1~2초). 주 모델은 다시 만들 때 글자 수를 잘 못 맞춘다
            shorter = await shorten_lines(ctx, strategy, limits, inp.topic)
            if shorter is not None:
                strategy = shorter
                fatal, fixable, notes = review(strategy, inp.duration_sec, names, compared)
        ctx.stats["s4_attempts"] = attempt
        if not fatal and not fixable:
            break
        feedback = fatal + fixable
        if attempt < MAX_ATTEMPTS:
            retries.append(",".join(sorted({retry_kind(m) for m in feedback})))
        if attempt == MAX_ATTEMPTS:
            if fatal:
                raise StepInputError(
                    f"전략을 {MAX_ATTEMPTS}회 만들었지만 고치지 못했다: " + "; ".join(fatal)
                )
            notes = fixable + notes
    # 대사가 짧으면 경량 모델로 한 번만 보강한다. 주 모델로 다시 만들면 하루 무료 한도를 쓰므로
    # 보강에 실패해도 다시 만들지 않고 알리기만 한다 (5단계가 속도·여백으로 길이를 맞춘다)
    minimums = line_minimums(strategy, inp.duration_sec)
    if minimums:
        longer = await lengthen_lines(ctx, strategy, minimums, inp.topic)
        if longer is not None:
            strategy = longer
            _, still, rest = review(strategy, inp.duration_sec, names, compared)
            notes = still + rest  # 고치지 못한 교정 문제(예: 전체 길이)는 경고로 남긴다
        else:
            notes.append(short_message(strategy, inp.duration_sec))
    for n in notes:
        ctx.warn(n)
    # 화면에 그대로 보이는 문장이라 입력의 내부 표기가 새지 않게 한다
    plain = SCOPE_TAG.sub("", strategy.differentiator).strip()
    return strategy.model_copy(update={"differentiator": plain})


def factor_line(f: Factor) -> str:
    """S4 입력의 요인 한 줄. 포맷 패턴은 구성에 쓸 수 있게 자세히 적는다."""
    # 제목·댓글에서 뽑은 내용이라 외부 텍스트로 다룬다 (줄을 흉내 내지 못하게 한 줄로)
    if f.name != "format":
        return f"- {f.name} ({f.confidence}): {wrap_untrusted(' '.join(f.finding.split()))}"
    parts = [
        f"{label}: {value}"
        for label, value in (
            ("훅", f.hook_type),
            ("전개", f.structure),
            ("감정", f.emotion),
            ("결말", f.ending),
        )
        if value
    ]
    scope = f" [{f.scope}]" if f.scope else ""
    body = " ".join(f"{f.finding} ({', '.join(parts)})".split())
    return f"- format{scope}: {wrap_untrusted(body)}"


def retry_kind(message: str) -> str:
    """review() 문제 문구의 종류 (metrics용, 내용 없이)."""
    for kind, mark in (
        ("hook_timing", "첫 장면은"),
        ("title_similar", "제목 '"),
        ("duration", "전체 길이"),
        ("hook_line", "훅 대사"),
        ("total_chars", "대사가 총"),
    ):
        if message.startswith(mark):
            return kind
    return "other"


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

    ref_tokens = [title_tokens(t) for t in ref_titles]
    for title in strategy.titles:
        mine = title_tokens(title)
        for toks in ref_tokens:
            if jaccard(mine, toks) > TITLE_JACCARD_MAX:
                fatal.append(f"제목 '{title}'이 레퍼런스 제목과 너무 비슷하다 — 다르게 쓴다")
                break

    total = scenes[-1].end
    if abs(total - duration_sec) > duration_sec * DURATION_TOLERANCE:
        fixable.append(f"전체 길이 {total:g}초를 목표 {duration_sec}초(±15%)에 맞춘다")

    # 대사 분량: 계획한 시간은 TTS가 실제로 읽는 길이와 맞아야 한다 (실측 약 6.8자/초)
    fixable += length_messages(strategy, duration_sec)

    for prev, cur in zip(scenes, scenes[1:], strict=False):
        if abs(cur.start - prev.end) > 0.05:
            notes.append(f"{prev.id}→{cur.id} 시간이 이어지지 않는다 ({prev.end:g}→{cur.start:g})")
    for s in scenes[1:]:
        length = s.end - s.start
        if not SCENE_MIN <= length <= SCENE_MAX:
            notes.append(f"{s.id} 길이 {length:.1f}초가 권장 범위(2~8초)를 벗어난다")
    return fatal, fixable, notes


def drop_unknown_refs(strategy: Strategy, factor_names: set[str]) -> Strategy:
    """분석에 없는 요인 참조는 지운다. 사용자가 할 일이 없는 경고라 매번 다른 경고를 가렸다."""
    scenes = [
        s.model_copy(update={"factor_refs": [f for f in s.factor_refs if f in factor_names]})
        for s in strategy.scenes
    ]
    return strategy.model_copy(update={"scenes": scenes})


# ── 대사 길이 ───────────────────────────────────────────


def _hook_limit(first: Scene) -> int:
    return round((first.end - first.start) * CHARS_PER_SEC) + HOOK_SLACK_CHARS


def char_budget(strategy: Strategy, duration_sec: int) -> int:
    """권장 대사 총 글자 수: (목표 길이 − 장면 여백 합계) × 초당 글자 수."""
    pads = SCENE_PAD * len(strategy.scenes) + LAST_SCENE_EXTRA_PAD
    return round((duration_sec - pads) * CHARS_PER_SEC)


def _total_over(strategy: Strategy, duration_sec: int) -> tuple[int, int] | None:
    """(대사 총 글자 수, 권장 글자 수). 권장보다 15% 넘게 길 때만."""
    chars = sum(len(s.line.strip()) for s in strategy.scenes)
    budget = char_budget(strategy, duration_sec)
    return (chars, budget) if chars > budget * (1 + DURATION_TOLERANCE) else None


def _total_under(strategy: Strategy, duration_sec: int) -> tuple[int, int] | None:
    """(대사 총 글자 수, 권장 글자 수). 권장보다 15% 넘게 짧을 때만.

    짧으면 5단계가 말하기 속도를 늦춰 길이를 맞추는데, -18%쯤 되면 목소리가 늘어져 들렸다
    (2026-10 실측: 126~146자 프로젝트가 모두 -17~-20%).
    """
    chars = sum(len(s.line.strip()) for s in strategy.scenes)
    budget = char_budget(strategy, duration_sec)
    return (chars, budget) if chars < budget * (1 - DURATION_TOLERANCE) else None


def line_minimums(strategy: Strategy, duration_sec: int) -> dict[str, int]:
    """보강할 장면과 그 대사의 최소 글자 수.

    훅은 짧아야 하므로 빼고, 장면 길이 × 6.8자/초의 90%.
    """
    if not _total_under(strategy, duration_sec):
        return {}
    out: dict[str, int] = {}
    for s in strategy.scenes[1:]:
        target = round((s.end - s.start) * CHARS_PER_SEC * 0.9)
        if len(s.line.strip()) < target:
            out[s.id] = target
    return out


def line_limits(strategy: Strategy, duration_sec: int) -> dict[str, int]:
    """줄여야 하는 장면과 그 대사의 최대 글자 수.

    - 훅: 장면 길이 × 6.8자/초 + 여유 4자
    - 대사 총량이 길면: 장면 길이 × 6.8자/초를 넘는 장면 모두 (합치면 권장 총량 안에 든다)
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


def short_message(strategy: Strategy, duration_sec: int) -> str:
    chars, budget = _total_under(strategy, duration_sec) or (0, 0)
    return (
        f"대사가 총 {chars}자로 {duration_sec}초에 비해 짧다 — {budget}자 안팎으로 보강하면 "
        "목소리가 늘어지지 않는다"
    )


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


class LongerOut(BaseModel):
    scenes: list[ShortLine]


async def lengthen_lines(
    ctx: StepContext, strategy: Strategy, minimums: dict[str, int], topic: str
) -> Strategy | None:
    """짧은 대사만 경량 LLM 1회로 보강한 전략. 실패하면 None (그때는 전략 전체를 다시 만든다)."""
    if not minimums:
        return None
    lines = [
        f"{s.id} role={s.role} "
        + (
            f"min_chars={minimums[s.id]} max_chars={round(minimums[s.id] * 1.2)} "
            f"(지금 {len(s.line.strip())}자) "
            if s.id in minimums
            else ""
        )
        + f"line={s.line.strip()!r}"
        for s in strategy.scenes
    ]
    user = f"topic: {topic}\n보강할 장면: {', '.join(minimums)}\n\n" + "\n".join(lines)
    try:
        out = await ctx.adapters.llm.generate_json(
            "s4_lengthen", load_prompt("s4_lengthen").text, user, LongerOut
        )
    except Exception:  # noqa: BLE001 - 보강은 보조 수단이다. 실패하면 다시 만든다
        return None
    new = {
        x.id: x.line.strip()
        for x in out.scenes
        if x.id in minimums and len(x.line.strip()) > len(_line(strategy, x.id))
    }
    if not new:
        return None
    scenes = [s.model_copy(update={"line": new.get(s.id, s.line)}) for s in strategy.scenes]
    return strategy.model_copy(update={"scenes": scenes})


def _line(strategy: Strategy, scene_id: str) -> str:
    return next((s.line.strip() for s in strategy.scenes if s.id == scene_id), "")
