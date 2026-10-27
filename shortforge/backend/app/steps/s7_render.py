"""S7 렌더: MP4(1080×1920) + SRT + 로그 (F-7.1~F-7.3) + 내보내기 전 자동 점검."""

from __future__ import annotations

from pathlib import Path

from app.adapters.base import RenderResult
from app.orchestrator import StepContext
from app.schemas.project import Input, Render, RenderCheck, Timeline

# 렌더 방식 버전. 화면이 "새 방식으로 다시 렌더"를 권하는 기준이다. 렌더 결과가 눈에 띄게
# 달라지는 변경(자막·색·장식·소리 처리)을 하면 올린다.
# 1: 기본  2: 자막 디자인·색 보정·끝 페이드(2026-10-24)  3: 엔딩 카드·번호 배지·방송용 목소리
# 4: 밝은 장면 자막 뒤 판(2026-10-27)
RENDER_QUALITY = 4

DURATION_TOLERANCE = 0.15  # 목표 길이 ±15% (5단계 음성 길이 보정과 같은 기준)
LOUDNESS_TARGET = -14.0
LOUDNESS_TOLERANCE = 1.5  # LUFS
EDGE_SEC = 0.5  # 처음·끝의 조용한 부분(페이드)은 무음으로 치지 않는다


async def run(ctx: StepContext) -> Render:
    timeline: Timeline = ctx.read("timeline")
    inp: Input = ctx.read("input")
    result = await ctx.adapters.video.render(timeline, ctx.project_dir, ctx.progress)

    def rel(p) -> str:
        try:
            return p.relative_to(ctx.project_dir).as_posix()
        except ValueError:
            return str(p)

    checks = render_checks(result, inp.duration_sec)
    for c in checks:
        if not c.ok:
            ctx.warn(f"자동 점검: {c.detail}")
    return Render(
        path=rel(result.path),
        srt=rel(result.srt),
        duration_sec=round(result.duration_sec, 2),
        log=rel(result.log),
        quality=RENDER_QUALITY,
        checks=checks,
    )


def render_checks(r: RenderResult, target_sec: float) -> list[RenderCheck]:
    """길이·음량·무음·자막 폭. 측정하지 못한 항목(음량)은 빼고 돌려준다."""
    dur = r.duration_sec
    checks: list[RenderCheck] = []
    if dur > 0:
        off = (dur - target_sec) / target_sec
        checks.append(
            RenderCheck(
                id="duration",
                ok=abs(off) <= DURATION_TOLERANCE,
                detail=f"길이 {dur:.1f}초 (목표 {target_sec}초"
                + ("" if abs(off) <= DURATION_TOLERANCE else f", {off:+.0%}: 4단계 대사를 조절")
                + ")",
            )
        )
    if r.loudness_lufs is not None:
        ok = abs(r.loudness_lufs - LOUDNESS_TARGET) <= LOUDNESS_TOLERANCE
        checks.append(
            RenderCheck(
                id="loudness",
                ok=ok,
                detail=f"음량 {r.loudness_lufs:.1f} LUFS (기준 {LOUDNESS_TARGET:.0f})"
                + ("" if ok else ": 플랫폼이 소리를 줄이거나 작게 들린다"),
            )
        )
    gaps = [(s, d) for s, d in r.silences if s > EDGE_SEC and s + d < dur - EDGE_SEC]
    checks.append(
        RenderCheck(
            id="silence",
            ok=not gaps,
            detail="말이 끊긴 구간 없음"
            if not gaps
            else "소리가 끊긴 구간 "
            + ", ".join(f"{s:.1f}초부터 {d:.1f}초" for s, d in gaps[:3])
            + ": 5단계 음성을 확인",
        )
    )
    wide = r.wide_captions
    checks.append(
        RenderCheck(
            id="caption_width",
            ok=not wide,
            detail="자막이 모두 화면 폭 안"
            if not wide
            else f'화면 폭을 넘는 자막 {len(wide)}개 (예: "{wide[0][:20]}"): 대사를 짧게',
        )
    )
    return checks


def rendered_quality(project_dir: Path, render: Render) -> int:
    """이 렌더의 방식 버전. 값을 남기기 전 렌더는 자막 파일의 흔적으로 어림한다."""
    if render.quality:
        return render.quality
    try:
        ass = (project_dir / "render" / "work" / "subs.ass").read_text(encoding="utf-8")
    except OSError:
        return 1
    if "Style: dim," in ass:
        return 3
    if "\\blur" in ass:
        return 2
    return 1
