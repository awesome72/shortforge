"""S6 합성 지시서: Timeline 생성 (F-6.1, PROJECT_PROMPT §6).

1. 규칙 기반 타임라인을 먼저 만든다 — 파일 경로·길이는 항상 여기서 정해진다(결정론적).
2. LLM은 장면별 연출(모션·전환·자막 스타일)만 고른다. 스키마 검증 실패는 어댑터가
   오류를 넣어 2회 재시도한다.
3. LLM이 실패하거나 장면 ID가 하나도 맞지 않으면 규칙 기반 연출을 그대로 쓴다(폴백).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.llm import load_prompt
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import (
    Asset,
    Caption,
    Motion,
    Strategy,
    Timeline,
    TimelineScene,
    Transition,
)

PAD = 0.2
MOTIONS = ("zoom_in", "pan_left", "zoom_out", "pan_right")
CAPTION_STYLE = {"hook": "hook_bold", "payoff": "emphasis"}
DURATION_TOLERANCE = 0.15


class SceneStyle(BaseModel):
    id: str
    motion: Motion
    transition: Transition
    caption_style: Literal["hook_bold", "body", "emphasis"]


class TimelineStyleOut(BaseModel):
    scenes: list[SceneStyle]


async def run(ctx: StepContext) -> Timeline:
    strategy: Strategy = ctx.read("strategy")
    assets = {a.scene_id: a for a in ctx.read("assets")}
    timeline = build_timeline(ctx, strategy, assets)
    if ctx.settings.s6_use_llm:
        await apply_llm_style(ctx, strategy, timeline)
    return timeline


async def apply_llm_style(ctx: StepContext, strategy: Strategy, timeline: Timeline) -> None:
    lines = [
        f"{sc.id} role={s.role} duration={sc.duration}s line={s.line!r} visual={s.visual!r}"
        for s, sc in zip(strategy.scenes, timeline.scenes, strict=True)
    ]
    try:
        out = await ctx.adapters.llm.generate_json(
            "s6_timeline", load_prompt("s6_timeline").text, "\n".join(lines), TimelineStyleOut
        )
    except Exception as e:
        ctx.warn(f"연출 생성에 실패해 규칙 기반 연출을 썼다 ({type(e).__name__})")
        return
    styles = {x.id: x for x in out.scenes}
    matched = 0
    for i, sc in enumerate(timeline.scenes):
        st = styles.get(sc.id)
        if st is None:
            continue
        matched += 1
        sc.motion = st.motion
        sc.caption.style = st.caption_style
        if i > 0:  # 첫 장면에는 앞 장면이 없으므로 전환을 두지 않는다
            sc.transition = st.transition
    if matched == 0:
        ctx.warn("연출 결과의 장면 ID가 맞지 않아 규칙 기반 연출을 썼다")
    elif matched < len(timeline.scenes):
        ctx.warn(f"{len(timeline.scenes) - matched}개 장면은 규칙 기반 연출을 썼다")


def build_timeline(ctx: StepContext, strategy: Strategy, assets: dict[str, Asset]) -> Timeline:
    missing = [s.id for s in strategy.scenes if not _ready(assets.get(s.id))]
    if missing:
        raise StepInputError(f"이미지나 음성이 없는 장면이 있다: {', '.join(missing)}")

    scenes = []
    for i, s in enumerate(strategy.scenes):
        a = assets[s.id]
        duration = (
            round(a.voice.duration_sec + PAD, 2) if a.voice.duration_sec is not None else "auto"
        )
        scenes.append(
            TimelineScene(
                id=s.id,
                image=a.image.path,
                voice=a.voice.path,
                duration=duration,
                pad=PAD,
                motion=Motion(type="zoom_in" if s.role == "hook" else MOTIONS[i % len(MOTIONS)]),
                transition=Transition(type="cut" if i == 0 else "fade", dur=0.0 if i == 0 else 0.2),
                caption=Caption(text=a.voice.text, style=CAPTION_STYLE.get(s.role, "body")),
            )
        )

    timeline = Timeline(scenes=scenes)
    known = [sc.duration for sc in scenes if isinstance(sc.duration, float)]
    if len(known) == len(scenes):
        total = sum(known)
        target = strategy.scenes[-1].end
        if abs(total - target) > target * DURATION_TOLERANCE:
            ctx.warn(f"음성 기준 길이 {total:.1f}초가 목표 {target:.0f}초의 ±15%를 벗어난다")
    return timeline


def _ready(asset: Asset | None) -> bool:
    return asset is not None and bool(asset.image.path) and bool(asset.voice.path)
