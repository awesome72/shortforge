"""S6 합성 지시서: Timeline 생성 (F-6.1).

지금은 규칙 기반 타임라인만 만든다. 이것은 PROJECT_PROMPT §6의 최종 폴백이기도 하다.
LLM 생성 → 스키마 검증 → 2회 재시도 경로는 Step 5에서 앞에 붙인다.
"""

from __future__ import annotations

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


async def run(ctx: StepContext) -> Timeline:
    strategy: Strategy = ctx.read("strategy")
    assets = {a.scene_id: a for a in ctx.read("assets")}
    return build_timeline(ctx, strategy, assets)


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
                caption=Caption(text=s.line, style=CAPTION_STYLE.get(s.role, "body")),
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
