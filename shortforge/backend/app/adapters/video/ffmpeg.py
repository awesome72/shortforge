"""FFmpeg 렌더러 (S7 기본 엔진, PROJECT_PROMPT §7 S7).

1. 장면 클립: 이미지 → cover 크롭 → zoompan 모션 → 무음 H.264 (장면끼리 병렬)
2. 합성:     xfade 전환 체인 + 음성 adelay 배치 + (BGM sidechaincompress 덕킹) + ASS 자막 번인
3. 인코딩:   H.264 CRF 20, AAC 192k, faststart

시간 배치: 장면 k의 시작 S_k = d_0 + … + d_(k-1), 여기서 d = 장면 길이(음성 + pad).
전환 T_k는 S_k 직전 T_k초 동안 겹친다. 그래서 클립 k는 앞쪽에 T_k만큼 더 길게 만들고
음성 k는 정확히 S_k에 시작한다. 총 길이 = Σd.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from app import music
from app.adapters.base import ProgressFn, RenderResult, VideoAdapter
from app.media import find_exe, probe_duration, run
from app.schemas.project import Timeline, TimelineScene
from app.subtitles import (
    Cue,
    Word,
    cues_from_text,
    cues_from_words,
    find_font,
    shift,
    to_ass,
    to_srt,
)

# 슬라이드는 값싸 보여(2026-10 점검) 크로스페이드로 바꿔 쓴다. 예전 지시서의 slide도 같다
XFADE = {"fade": "fade", "slide": "fade"}
MAX_MOTION = 0.12  # 이보다 큰 확대·이동은 어지럽고 화질이 떨어진다
END_FADE_SEC = 0.5  # 마지막에 화면·소리를 살짝 닫는다
# 색 보정(합성 뒤, 자막 앞에 한 번): 무료 사진·AI 그림이 섞여도 한 작품처럼 보이게
# (장면 클립 단계, 합성 단계). 무거운 보정은 병렬·캐시되는 클립 단계에 둔다:
# 합성 단계에 colorbalance(RGB)·vignette를 두었더니 30초 영상 합성이
# 62초 → 182초가 됐다(2026-10-24). 따뜻한 톤은 YUV 표(lutyuv)로 색차를 살짝 옮겨
# RGB 변환 없이 낸다. 그레인은 프레임마다 달라야 해 합성 단계에 둔다
GRADES: dict[str, tuple[str, str]] = {
    "film": (
        "eq=contrast=1.05:saturation=0.94:gamma=0.98,lutyuv=u=val-2:v=val+2,vignette=angle=PI/7",
        "noise=alls=3:allf=t",
    ),
    "clean": ("eq=contrast=1.03", ""),
    "off": ("", ""),
}
# 음량 정규화 (Step 7-2). YouTube 등 플랫폼 기준 -14 LUFS, true peak -1.5 dBTP.
# loudnorm은 내부적으로 192kHz로 올리므로 48kHz로 되돌린다. 피크 제한도 loudnorm이 한다.
LOUDNESS_LUFS = -14
LOUDNORM = f"loudnorm=I={LOUDNESS_LUFS}:TP=-1.5:LRA=11,aresample=48000"
# 장면 클립 재사용 키에 들어간다. 클립을 만드는 방식(필터·인코딩)을 바꾸면 올린다
CLIP_VERSION = 2  # 2: 움직임 가감속, 클립 끝 한 프레임 여유
CLIP_CRF = 18
CAPTION_TO_ASS = {"hook_bold": "hook_bold", "emphasis": "emphasis", "body": "body"}


@dataclass
class _Plan:
    scene: TimelineScene
    image: Path
    voice: Path
    duration: float  # d_k
    lead: float  # T_k (앞 장면과 겹치는 전환 길이)
    start: float  # S_k
    words: list[Word] | None


@dataclass
class _Log:
    path: Path
    lines: list[str] = field(default_factory=list)
    t0: float = field(default_factory=time.perf_counter)
    timings: dict[str, float] = field(default_factory=dict)

    def write(self, line: str) -> None:
        self.lines.append(line)
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")

    def stage(self, name: str, started: float) -> None:
        self.timings[name] = round(time.perf_counter() - started, 2)
        self.write(f"[timing] {name}: {self.timings[name]}s")


class FFmpegRenderer(VideoAdapter):
    async def make_bgm(self, out: Path, mood: str, duration: float, seed: int) -> Path:
        return await music.render_bgm(out, mood, duration, seed)

    def __init__(
        self,
        *,
        preset: str = "veryfast",
        font: str = "auto",
        workers: int | None = None,
        grade: str = "film",
        supersample: float = 1.5,
        clip_preset: str | None = None,
    ) -> None:
        self.preset = preset
        # 장면 클립(중간 파일)의 인코딩 preset. 합성 때 다시 인코딩하므로 따로 둘 수 있다
        self.clip_preset = clip_preset or preset
        self.font, self.font_file = find_font(font)
        self.clip_grade, self.grade = GRADES.get(grade, GRADES["off"])
        self.workers = workers or max(1, (os.cpu_count() or 2) // 2)
        self.supersample = supersample
        self.last_timings: dict[str, float] = {}

    async def render(
        self, timeline: Timeline, project_dir: Path, progress: ProgressFn
    ) -> RenderResult:
        out_dir = project_dir / "render"
        work = out_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        log = _Log(out_dir / "render.log")
        log.write(f"ShortForge FFmpeg render · preset={self.preset} workers={self.workers}")

        plans = await self._plan(timeline, project_dir)
        total = round(sum(p.duration for p in plans), 3)
        log.write(f"scenes={len(plans)} total={total}s")

        # 1. 장면 클립 (병렬)
        t = time.perf_counter()
        sem = asyncio.Semaphore(self.workers)
        done = 0

        async def one(i: int, p: _Plan) -> Path:
            nonlocal done
            async with sem:
                path = await self._clip(timeline, p, work, log)
            done += 1
            await progress("clips", done / len(plans))
            return path

        clips = await asyncio.gather(*(one(i, p) for i, p in enumerate(plans)))
        log.stage("clips", t)

        # 2. 자막
        t = time.perf_counter()
        cues = self._cues(timeline, plans)
        srt = out_dir / "final.srt"
        srt.write_text(to_srt(cues), encoding="utf-8")
        ass = work / "subs.ass"
        ass.write_text(
            to_ass(cues, timeline.canvas.w, timeline.canvas.h, self.font), encoding="utf-8"
        )
        log.stage("subtitles", t)

        # 3. 합성 + 인코딩
        t = time.perf_counter()
        final = out_dir / "final.mp4"
        await self._compose(timeline, plans, clips, ass, final, total, project_dir, log, progress)
        log.stage("compose", t)
        _prune_clips(work, keep=set(clips))

        log.timings["total"] = round(time.perf_counter() - log.t0, 2)
        log.write(f"[timing] total: {log.timings['total']}s")
        log.write("timings=" + json.dumps(log.timings))
        self.last_timings = dict(log.timings)
        return RenderResult(path=final, srt=srt, duration_sec=total, log=log.path)

    # ── 계획 ─────────────────────────────────────────────

    async def _plan(self, timeline: Timeline, project_dir: Path) -> list[_Plan]:
        plans: list[_Plan] = []
        start = 0.0
        frame = 1 / timeline.canvas.fps
        for i, sc in enumerate(timeline.scenes):
            image, voice = _resolve(project_dir, sc.image), _resolve(project_dir, sc.voice)
            for p in (image, voice):
                if not p.exists():
                    raise FileNotFoundError(f"{sc.id}: 파일이 없다: {p}")
            if sc.duration == "auto":
                duration = await probe_duration(voice) + sc.pad
            else:
                duration = float(sc.duration)
            lead = 0.0
            if i > 0:
                lead = frame if sc.transition.type == "cut" else max(sc.transition.dur, frame)
                lead = min(lead, plans[-1].duration / 2, duration / 2)
            plans.append(
                _Plan(sc, image, voice, round(duration, 3), lead, round(start, 3), _words(voice))
            )
            start += duration
        return plans

    # ── 1. 클립 ──────────────────────────────────────────

    async def _clip(self, timeline: Timeline, p: _Plan, work: Path, log: _Log) -> Path:
        """장면 클립 하나. 입력(이미지 파일·모션·길이·캔버스·인코딩)이 같은 클립이 있으면 다시 쓴다.

        자막·BGM·전환만 바꿔 다시 렌더할 때 클립 인코딩(렌더 시간의 약 40%)을 건너뛴다.
        """
        c = timeline.canvas
        length = p.lead + p.duration
        # 올림 + 한 프레임 여유: 반올림으로 한 프레임이 모자라면 앞 클립이
        # 다음 전환(컷은 1프레임)이 시작하기 전에 끝나 xfade가 거기서 영상을 끊었다
        # (2026-10-24: 32초 영상의 화면이 17초에서 끝남).
        # 남는 프레임은 다음 xfade가 잘라 내고, 마지막 클립은 -t로 전체 길이에 맞춘다
        frames = max(1, math.ceil(length * c.fps - 1e-6) + 1)
        sw, sh = _even(c.w * self.supersample), _even(c.h * self.supersample)
        vf = (
            f"scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},setsar=1,"
            f"{_zoompan(p.scene.motion.type, p.scene.motion.amount, frames, c.w, c.h, c.fps)},"
            + (f"{self.clip_grade}," if self.clip_grade else "")
            + "format=yuv420p"
        )
        args = [
            find_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(p.image),
            "-vf", vf,
            "-frames:v", str(frames),
            "-c:v", "libx264", "-preset", self.clip_preset, "-crf", str(CLIP_CRF),
            "-threads", "2", "-an",
        ]  # fmt: skip
        stat = p.image.stat()
        # args[5:]는 입력 경로·필터(모션·길이·캔버스)·인코딩 설정이다.
        # 같은 경로의 파일을 바꾸면 크기·수정 시각이 바뀌어 다시 만든다
        key = json.dumps(
            [CLIP_VERSION, stat.st_size, stat.st_mtime_ns, args[5:]], ensure_ascii=False
        )
        out = work / f"clip_{hashlib.sha256(key.encode()).hexdigest()[:16]}.mp4"
        if out.is_file() and out.stat().st_size > 0:
            log.write(f"clip {p.scene.id}: {length:.2f}s {frames}f 재사용")
            return out
        # 끊긴 파일을 재사용하지 않게 임시 이름으로 만든 뒤 바꾼다
        part = out.with_name(out.stem + ".part.mp4")
        t = time.perf_counter()
        await run([*args, str(part)])
        os.replace(part, out)
        log.write(f"clip {p.scene.id}: {length:.2f}s {frames}f {time.perf_counter() - t:.1f}s")
        return out

    def _font_dir(self, work: Path) -> Path | None:
        """고른 글꼴 파일을 작업 폴더에 복사한다 (사용자 폴더에만 설치된 글꼴도 쓰이게)."""
        if self.font_file is None:
            return None
        fonts = work / "fonts"
        fonts.mkdir(parents=True, exist_ok=True)
        dest = fonts / self.font_file.name
        if not dest.exists():
            shutil.copy2(self.font_file, dest)
        return fonts

    # ── 2. 자막 큐 ───────────────────────────────────────

    def _cues(self, timeline: Timeline, plans: list[_Plan]) -> list[Cue]:
        max_chars = timeline.subtitles.max_chars_per_line
        cues: list[Cue] = []
        for p in plans:
            style = CAPTION_TO_ASS[p.scene.caption.style]
            if p.words:
                local = cues_from_words(p.words, max_chars, style, p.scene.caption.text)
            else:
                local = cues_from_text(
                    p.scene.caption.text, p.duration - p.scene.pad, max_chars, style
                )
            for c in local:  # 다음 장면으로 넘어가지 않게 자른다
                c.end = min(c.end, p.duration)
            cues.extend(shift(local, p.start))
        return cues

    # ── 3. 합성 ──────────────────────────────────────────

    async def _compose(
        self,
        timeline: Timeline,
        plans: list[_Plan],
        clips: list[Path],
        ass: Path,
        final: Path,
        total: float,
        project_dir: Path,
        log: _Log,
        progress: ProgressFn,
    ) -> None:
        n = len(plans)
        inputs: list[str] = []
        for clip in clips:
            inputs += ["-i", str(clip)]
        for p in plans:
            inputs += ["-i", str(p.voice)]
        bgm = timeline.audio.bgm
        if bgm:
            inputs += ["-stream_loop", "-1", "-i", str(_resolve(project_dir, bgm))]

        g: list[str] = []
        # 비디오: xfade 체인
        prev = "0:v"
        for k in range(1, n):
            p = plans[k]
            kind = XFADE.get(p.scene.transition.type, "fade")
            g.append(
                f"[{prev}][{k}:v]xfade=transition={kind}:duration={p.lead:.3f}:"
                f"offset={p.start - p.lead:.3f}[x{k}]"
            )
            prev = f"x{k}"
        vchain = f"[{prev}]"
        fade_at = max(0.0, total - END_FADE_SEC)
        fade_out = f"afade=t=out:st={fade_at:.3f}:d={END_FADE_SEC}"
        look = f"{self.grade}," if self.grade else ""
        g.append(f"{vchain}{look}fade=t=out:st={fade_at:.3f}:d={END_FADE_SEC}[vgrade]")
        vchain = "[vgrade]"
        if timeline.subtitles.burn_in:
            rel_ass = ass.relative_to(
                project_dir
            ).as_posix()  # cwd=project_dir → 경로 이스케이프 불필요
            fonts = self._font_dir(final.parent / "work")
            opt = f":fontsdir='{fonts.relative_to(project_dir).as_posix()}'" if fonts else ""
            g.append(f"{vchain}ass='{rel_ass}'{opt}[vsub]")
            vchain = "[vsub]"
        g.append(f"{vchain}format=yuv420p[vout]")

        # 오디오: 음성을 각 장면 시작에 배치
        for k, p in enumerate(plans):
            ms = round(p.start * 1000)
            g.append(
                f"[{n + k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"adelay=delays={ms}:all=1[a{k}]"
            )
        mix_in = "".join(f"[a{k}]" for k in range(n))
        g.append(
            f"{mix_in}amix=inputs={n}:normalize=0:dropout_transition=0,"
            f"apad,atrim=0:{total:.3f}[voice]"
        )
        if bgm:
            a = timeline.audio
            # duck_db(-12) → 압축비. 대략 음성 구간에서 BGM이 duck_db만큼 내려가도록 잡은 값
            ratio = max(2.0, min(20.0, abs(a.duck_db) / 1.5))
            g.append("[voice]asplit=2[vmain][vsc]")
            g.append(
                f"[{2 * n}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"volume={a.bgm_gain_db}dB,atrim=0:{total:.3f}[bg]"
            )
            g.append(
                f"[bg][vsc]sidechaincompress=threshold=0.02:ratio={ratio:.1f}:"
                "attack=20:release=400[bgd]"
            )
            g.append(f"[vmain][bgd]amix=inputs=2:normalize=0,{LOUDNORM},{fade_out}[aout]")
        else:
            g.append(f"[voice]{LOUDNORM},{fade_out}[aout]")

        graph = ";\n".join(g)
        (final.parent / "work" / "graph.txt").write_text(graph, encoding="utf-8")
        args = [
            find_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
            "-progress", "pipe:1", "-nostats",
            *inputs,
            "-filter_complex", graph,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", self.preset, "-crf", "20",
            "-r", str(timeline.canvas.fps), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total:.3f}",
            "-movflags", "+faststart",
            str(final),
        ]  # fmt: skip

        async def on_line(line: str) -> None:
            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                except ValueError:
                    return
                await progress("compose", min(us / 1e6 / total, 1.0))

        log.write("compose: filter_complex → work/graph.txt")
        await run(args, cwd=project_dir, on_line=on_line)


def _resolve(project_dir: Path, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else project_dir / p


def _words(voice: Path) -> list[Word] | None:
    wp = voice.with_suffix(".words.json")
    if not wp.exists():
        return None
    data = json.loads(wp.read_text(encoding="utf-8"))
    return [Word(w["text"], w["start"], w["end"]) for w in data] or None


def _even(x: float) -> int:
    return int(round(x / 2) * 2)


def _prune_clips(work: Path, keep: set[Path]) -> None:
    """이번 렌더에 쓰지 않은 장면 클립을 지운다 (장면을 바꿀 때마다 쌓이지 않게)."""
    for f in work.glob("clip_*.mp4"):
        if f not in keep:
            try:
                f.unlink()
            except OSError:
                pass  # 다른 프로그램이 열고 있으면 다음 렌더 때 지운다


def _zoompan(kind: str, amount: float, frames: int, w: int, h: int, fps: int) -> str:
    """zoompan 식. on = 출력 프레임 번호(0..frames-1).

    일정한 속도로 움직이면 기계적으로 보여, 천천히 출발해 천천히 멈추는 곡선(코사인)을 쓴다.
    """
    n = max(frames - 1, 1)
    amount = min(amount, MAX_MOTION)
    ease = f"(1-cos(PI*on/{n}))/2"
    center_x, center_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if kind == "zoom_in":
        z, x, y = f"1+{amount}*{ease}", center_x, center_y
    elif kind == "zoom_out":
        z, x, y = f"1+{amount}*(1-{ease})", center_x, center_y
    elif kind == "pan_left":
        z, x, y = f"{1 + amount}", f"(iw-iw/zoom)*(1-{ease})", center_y
    elif kind == "pan_right":
        z, x, y = f"{1 + amount}", f"(iw-iw/zoom)*{ease}", center_y
    else:
        z, x, y = "1", "0", "0"
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps}"
