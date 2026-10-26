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
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from app import music
from app.adapters.base import ProgressFn, RenderResult, VideoAdapter
from app.media import (
    MediaError,
    available_memory_mb,
    find_exe,
    is_video_path,
    probe_duration,
    run,
)
from app.schemas.project import Timeline, TimelineScene
from app.subtitles import (
    Cue,
    Word,
    badge_number,
    cues_from_text,
    cues_from_words,
    find_font,
    shift,
    to_ass,
    to_srt,
    too_wide,
    wrap_title,
)

# 슬라이드는 값싸 보여(2026-10 점검) 크로스페이드로 바꿔 쓴다. 예전 지시서의 slide도 같다
XFADE = {"fade": "fade", "slide": "fade"}
MAX_MOTION = 0.12  # 이보다 큰 확대·이동은 어지럽고 화질이 떨어진다
END_FADE_SEC = 0.5  # 마지막에 화면·소리를 살짝 닫는다
END_CARD_SEC = 2.4  # 채널 이름이 있으면 마지막 이만큼 엔딩 카드를 띄운다
# 방송용 목소리: 저음 웅웅거림을 자르고, 또렷함(3kHz 부근)을 살짝 올리고, 크기를 고르게 누른다
VOICE_CHAIN = (
    "highpass=f=80,equalizer=f=3200:t=q:w=1.0:g=2.5,"
    "acompressor=threshold=0.1:ratio=3:attack=5:release=80:makeup=1.5"
)
LOW_MEMORY_MB = 2500  # 남은 메모리가 이보다 적으면 장면 클립을 동시에 덜 만든다 (RAM 8GB PC)
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
# 내보내기 전 점검: 이보다 조용하고 긴 구간은 '말이 끊긴 곳'으로 본다
SILENCE_DB = -45
SILENCE_SEC = 1.5
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
        brand: str = "",
        supersample: float = 1.5,
        clip_preset: str | None = None,
    ) -> None:
        self.preset = preset
        # 장면 클립(중간 파일)의 인코딩 preset. 합성 때 다시 인코딩하므로 따로 둘 수 있다
        self.clip_preset = clip_preset or preset
        self.font, self.font_file = find_font(font)
        self.clip_grade, self.grade = GRADES.get(grade, GRADES["off"])
        self.fixed_workers = workers is not None
        self.workers = workers or max(1, (os.cpu_count() or 2) // 2)
        self.brand = brand.strip()
        self.supersample = supersample
        self.last_timings: dict[str, float] = {}

    async def render(
        self, timeline: Timeline, project_dir: Path, progress: ProgressFn
    ) -> RenderResult:
        out_dir = project_dir / "render"
        work = out_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        log = _Log(out_dir / "render.log")
        workers = self._workers_for_memory()
        log.write(f"ShortForge FFmpeg render · preset={self.preset} workers={workers}")
        if workers < self.workers:
            log.write(f"남은 메모리가 적어 장면 클립을 {workers}개씩 만든다 (저메모리)")

        plans = await self._plan(timeline, project_dir)
        total = round(sum(p.duration for p in plans), 3)
        log.write(f"scenes={len(plans)} total={total}s")

        # 1. 장면 클립 (병렬)
        t = time.perf_counter()
        sem = asyncio.Semaphore(workers)
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
        overlays = self._overlays(plans, total)
        ass.write_text(
            to_ass(cues + overlays, timeline.canvas.w, timeline.canvas.h, self.font),
            encoding="utf-8",
        )
        log.stage("subtitles", t)

        # 3. 합성 + 인코딩
        t = time.perf_counter()
        final = out_dir / "final.mp4"
        await self._compose(timeline, plans, clips, ass, final, total, project_dir, log, progress)
        log.stage("compose", t)
        _prune_clips(work, keep=set(clips))

        # 4. 내보내기 전 점검용 측정 (소리만 읽는다)
        t = time.perf_counter()
        lufs, silences = await self._measure(final, total, log)
        log.stage("measure", t)

        log.timings["total"] = round(time.perf_counter() - log.t0, 2)
        log.write(f"[timing] total: {log.timings['total']}s")
        log.write("timings=" + json.dumps(log.timings))
        self.last_timings = dict(log.timings)
        return RenderResult(
            path=final,
            srt=srt,
            duration_sec=total,
            log=log.path,
            loudness_lufs=lufs,
            silences=silences,
            wide_captions=too_wide(cues, timeline.canvas.w),
        )

    async def _measure(
        self, final: Path, total: float, log: _Log
    ) -> tuple[float | None, list[tuple[float, float]]]:
        """완성 영상의 통합 음량(LUFS)과 긴 무음 구간. 실패해도 렌더는 성공으로 둔다."""
        args = [
            find_exe("ffmpeg"), "-hide_banner", "-nostats", "-i", str(final), "-vn",
            "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_SEC},ebur128=framelog=verbose",
            "-f", "null", "-",
        ]  # fmt: skip
        try:
            err = await run(args)
        except MediaError as e:
            log.write(f"measure: 실패 {e}")
            return None, []
        lufs, silences = parse_loudness(err), parse_silences(err, total)
        log.write(f"measure: {lufs} LUFS, 무음 {silences}")
        return lufs, silences

    async def make_cover(
        self, image: Path, title: str, out: Path, width: int, height: int, project_dir: Path
    ) -> Path:
        """훅 장면 이미지(동영상이면 첫 프레임) + 제목 한 장 (영상과 같은 색 보정·글꼴)."""
        work = out.parent / "work"
        work.mkdir(parents=True, exist_ok=True)
        ass = work / "cover.ass"
        ass.write_text(
            to_ass([Cue(0, 10, wrap_title(title), "cover")], width, height, self.font),
            encoding="utf-8",
        )
        fonts = self._font_dir(work)
        opt = f":fontsdir='{fonts.relative_to(project_dir).as_posix()}'" if fonts else ""
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
            + (f"{self.clip_grade}," if self.clip_grade else "")
            + f"ass='{ass.relative_to(project_dir).as_posix()}'{opt}"
        )
        part = out.with_name(out.stem + ".part" + out.suffix)
        await run(
            [find_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(image), "-vf", vf, "-frames:v", "1", "-q:v", "2", str(part)],
            cwd=project_dir,
        )  # fmt: skip
        os.replace(part, out)
        return out

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
        if is_video_path(p.image):
            # 동영상 장면: 움직임은 영상 자체에 있다. 9:16으로 가운데를 잘라 쓰고,
            # 장면보다 짧으면 마지막 프레임에서 멈춘다(반복 재생은 어색하다)
            vf = (
                f"fps={c.fps},scale={c.w}:{c.h}:force_original_aspect_ratio=increase,"
                f"crop={c.w}:{c.h},setsar=1,"
                + (f"{self.clip_grade}," if self.clip_grade else "")
                + f"tpad=stop_mode=clone:stop_duration={length:.3f},format=yuv420p"
            )
        else:
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

    def _workers_for_memory(self) -> int:
        """설정에서 개수를 정하지 않았으면 남은 메모리에 맞춰 줄인다.

        RAM 8GB PC에서 메모리 부족으로 서버가 꺼진 일이 있다.
        """
        if self.fixed_workers:
            return self.workers
        free = available_memory_mb()
        if free is None or free >= LOW_MEMORY_MB:
            return self.workers
        return 1 if free < LOW_MEMORY_MB * 0.6 else min(self.workers, 2)

    def _overlays(self, plans: list[_Plan], total: float) -> list[Cue]:
        """화면에만 얹는 장식: 순서로 시작하는 장면의 번호 배지, 마지막 엔딩 카드(채널 이름)."""
        out: list[Cue] = []
        for p in plans:
            n = badge_number(p.scene.caption.text)
            if n is not None:
                out.append(Cue(p.start, p.start + p.duration, f"{n:02d}", "badge"))
        if self.brand:
            name = self.brand if self.brand.startswith("@") else f"@{self.brand}"
            start = max(0.0, total - END_CARD_SEC)
            out.append(Cue(start, total, "", "dim"))
            out.append(Cue(start, total, name, "brand"))
        return out

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
                f"{VOICE_CHAIN},adelay=delays={ms}:all=1[a{k}]"
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


def parse_loudness(stderr: str) -> float | None:
    """ebur128 요약의 통합 음량 (I: -14.0 LUFS). 마지막 값이 전체 요약이다."""
    found = re.findall(r"\bI:\s+(-?\d+(?:\.\d+)?) LUFS", stderr)
    return float(found[-1]) if found else None


def parse_silences(stderr: str, total: float) -> list[tuple[float, float]]:
    """silencedetect 출력 → (시작, 길이). 끝나지 않은 무음은 영상 끝까지로 본다."""
    out: list[tuple[float, float]] = []
    start: float | None = None
    for m in re.finditer(r"silence_(start|end): (-?\d+(?:\.\d+)?)", stderr):
        value = max(0.0, float(m.group(2)))
        if m.group(1) == "start":
            start = value
        elif start is not None:
            out.append((round(start, 2), round(value - start, 2)))
            start = None
    if start is not None:
        out.append((round(start, 2), round(max(0.0, total - start), 2)))
    return out


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
