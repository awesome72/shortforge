"""S7 렌더: MP4(1080×1920) + SRT + 로그 (F-7.1~F-7.3). 실제 FFmpeg 렌더러는 Step 2."""

from __future__ import annotations

from app.orchestrator import StepContext
from app.schemas.project import Render, Timeline


async def run(ctx: StepContext) -> Render:
    timeline: Timeline = ctx.read("timeline")
    result = await ctx.adapters.video.render(timeline, ctx.project_dir, ctx.progress)

    def rel(p) -> str:
        try:
            return p.relative_to(ctx.project_dir).as_posix()
        except ValueError:
            return str(p)

    return Render(
        path=rel(result.path),
        srt=rel(result.srt),
        duration_sec=round(result.duration_sec, 2),
        log=rel(result.log),
    )
