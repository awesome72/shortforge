"""배경음악 합성 (₩0, 저작권 걱정 없음).

GPU가 없는 PC에서도 몇 초 안에 만들 수 있게, 분위기마다 코드 진행·빠르기·악기 구성을 정해 두고
순수 파이썬으로 소리를 합성한다(패드·아르페지오·베이스·킥·하이햇). 음원을 내려받지 않으므로
라이선스·출처 표기가 필요 없다. 목소리 아래에 -18dB로 깔리고 렌더에서 덕킹되므로
단순한 음색으로 충분하다.

같은 (분위기, 길이, seed)는 같은 파일을 만든다. 만드는 방식을 바꾸면 MUSIC_VERSION을 올린다.
"""

from __future__ import annotations

import asyncio
import math
import random
import struct
import wave
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, get_args

from app.media import find_exe, run

if TYPE_CHECKING:
    from app.adapters.base import VideoAdapter
    from app.schemas.project import Timeline

MUSIC_VERSION = 1
SR = 22050

MoodName = Literal["calm", "warm", "upbeat", "inspiring", "focus", "playful", "tense"]

# 분위기 → 화면 이름 (S6 프롬프트·화면·체크리스트가 같은 목록을 쓴다)
MOOD_LABEL: dict[str, str] = {
    "calm": "잔잔한",
    "warm": "따뜻한",
    "upbeat": "경쾌한",
    "inspiring": "벅차오르는",
    "focus": "차분한 정보",
    "playful": "유쾌한",
    "tense": "긴장감 있는",
}
DEFAULT_MOOD = "warm"

# 장조 화음(근음에서 반음 거리). 단조는 tense만 쓴다
_I, _V, _VI, _IV = (0, 4, 7, 11), (7, 11, 14, 17), (9, 12, 16, 19), (5, 9, 12, 16)
_II = (2, 5, 9, 12)


@dataclass(frozen=True)
class Mood:
    bpm: int
    prog: tuple[tuple[int, ...], ...]  # 화음 하나 = 2마디
    arp: str  # none | quarter | eighth | bounce
    bass: str  # hold | beat | eighth | bounce
    kick: str  # none | half | beat
    hat: bool
    pad: float  # 패드 음량
    bright: float  # 아르페지오 배음 (0 = 둥근 소리)


MOODS: dict[str, Mood] = {
    "calm": Mood(68, (_I, _VI, _IV, _V), "quarter", "hold", "none", False, 0.55, 0.0),
    "warm": Mood(76, (_I, _V, _VI, _IV), "eighth", "hold", "none", False, 0.45, 0.15),
    "upbeat": Mood(112, (_I, _V, _VI, _IV), "eighth", "beat", "half", True, 0.25, 0.35),
    "inspiring": Mood(96, (_VI, _IV, _I, _V), "eighth", "eighth", "beat", True, 0.45, 0.25),
    "focus": Mood(88, (_I, _IV, _II, _IV), "quarter", "beat", "none", True, 0.35, 0.1),
    "playful": Mood(120, (_I, _IV, _V, _IV), "bounce", "bounce", "half", True, 0.2, 0.4),
    "tense": Mood(
        84,
        ((0, 3, 7, 10), (8, 12, 15, 19), (3, 7, 10, 14), (10, 14, 17, 21)),
        "eighth",
        "eighth",
        "half",
        False,
        0.5,
        0.2,
    ),
}

KEYS = (48, 50, 53, 55, 57)  # C3 D3 F3 G3 A3 — 프로젝트마다 seed로 하나를 고른다


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _tone(
    midi: float, sec: float, *, decay: float, bright: float, attack: float = 0.005
) -> list[float]:
    """한 음: 사인 + 배음, 짧은 어택 뒤 지수 감쇠."""
    f = _hz(midi)
    n = int(sec * SR)
    w = 2 * math.pi * f / SR
    a = max(1, int(attack * SR))
    out = []
    for i in range(n):
        env = (i / a if i < a else 1.0) * math.exp(-i / (decay * SR))
        s = math.sin(w * i)
        if bright:
            s += bright * math.sin(2 * w * i) + bright * 0.4 * math.sin(3 * w * i)
        out.append(s * env)
    return out


def _pad(chord: tuple[int, ...], root: int, sec: float) -> list[float]:
    """화음 패드: 음마다 살짝 어긋난 사인 두 개(넓게 퍼지는 소리), 천천히 올라오고 내려간다."""
    n = int(sec * SR)
    rise, fall = int(0.6 * SR), int(0.8 * SR)
    ws = []
    for st in chord:
        f = _hz(root + 12 + st)
        ws += [2 * math.pi * f * 0.9985 / SR, 2 * math.pi * f * 1.0015 / SR]
    k = 1.0 / len(ws)
    out = []
    for i in range(n):
        env = min(1.0, i / rise, (n - i) / fall)
        out.append(env * k * sum(math.sin(w * i) for w in ws))
    return out


def _kick() -> list[float]:
    n = int(0.28 * SR)
    out, ph = [], 0.0
    for i in range(n):
        t = i / SR
        ph += 2 * math.pi * (48 + 90 * math.exp(-t * 30)) / SR
        out.append(math.sin(ph) * math.exp(-t * 14))
    return out


def _hat(rng: random.Random) -> list[float]:
    n = int(0.05 * SR)
    out, prev = [], 0.0
    for i in range(n):
        x = rng.uniform(-1, 1)
        out.append((x - prev) * 0.5 * math.exp(-i / (0.012 * SR)))  # 차분 = 간단한 고역 통과
        prev = x
    return out


def _mix(buf: list[float], src: list[float], at: int, gain: float) -> None:
    if at >= len(buf):
        return
    end = min(len(buf), at + len(src))
    buf[at:end] = [a + gain * b for a, b in zip(buf[at:end], src, strict=False)]


def synth(mood: str, duration: float, seed: int) -> list[float]:
    """분위기·길이·seed로 모노 샘플(-1~1)을 만든다."""
    m = MOODS.get(mood) or MOODS[DEFAULT_MOOD]
    rng = random.Random(seed)
    root = rng.choice(KEYS)
    beat = 60.0 / m.bpm
    chord_sec = beat * 8  # 화음 하나 = 4/4 두 마디
    n = int((duration + 0.5) * SR)
    buf = [0.0] * n

    pads: dict[int, list[float]] = {}
    plucks: dict[float, list[float]] = {}
    bass_notes: dict[tuple[int, float], list[float]] = {}
    kick, hat = _kick(), _hat(rng)

    def pluck(midi: int, sec: float) -> list[float]:
        key = (midi, sec)
        if key not in plucks:
            plucks[key] = _tone(midi, sec, decay=0.22, bright=m.bright)
        return plucks[key]

    def bass(midi: int, sec: float) -> list[float]:
        key = (midi, sec)
        if key not in bass_notes:
            bass_notes[key] = _tone(midi, sec, decay=sec * 0.7, bright=0.25, attack=0.02)
        return bass_notes[key]

    t, ci = 0.0, 0
    while t < duration + 0.5:
        idx = ci % len(m.prog)
        chord = m.prog[idx]
        at = int(t * SR)
        if idx not in pads:
            pads[idx] = _pad(chord, root, chord_sec + 0.6)
        _mix(buf, pads[idx], at, m.pad)

        # 베이스
        r = root - 12 + chord[0]
        if m.bass == "hold":
            _mix(buf, bass(r, chord_sec), at, 0.45)
        else:
            step = {"beat": beat, "eighth": beat / 2, "bounce": beat}[m.bass]
            k = 0
            while k * step < chord_sec - 1e-6:
                note = r + (7 if m.bass == "bounce" and k % 2 else 0)
                _mix(buf, bass(note, step * 0.9), at + int(k * step * SR), 0.4)
                k += 1

        # 아르페지오
        if m.arp != "none":
            step = beat if m.arp == "quarter" else beat / 2
            tones = [root + 12 + s for s in chord] + [root + 24 + chord[0]]
            k = 0
            while k * step < chord_sec - 1e-6:
                if m.arp == "bounce":
                    note = rng.choice(tones) + (12 if rng.random() < 0.25 else 0)
                    if rng.random() < 0.2:  # 쉼표로 통통 튀는 느낌
                        k += 1
                        continue
                else:
                    seq = [0, 1, 2, 3, 2, 1] if m.arp == "eighth" else [0, 2, 1, 3]
                    note = tones[seq[k % len(seq)]]
                _mix(buf, pluck(note, min(0.6, step * 1.8)), at + int(k * step * SR), 0.28)
                k += 1

        # 리듬
        beats = int(round(chord_sec / beat))
        for b in range(beats):
            pos = at + int(b * beat * SR)
            if m.kick == "beat" or (m.kick == "half" and b % 2 == 0):
                _mix(buf, kick, pos, 0.55)
            if m.hat:
                _mix(buf, hat, pos + int(beat / 2 * SR), 0.18)
        t += chord_sec
        ci += 1

    peak = max(1e-6, max(abs(x) for x in buf))
    g = 0.85 / peak
    return [math.tanh(x * g) for x in buf]  # 부드럽게 눌러 클리핑을 막는다


def bgm_filename(mood: str, duration: float, seed: int) -> str:
    return f"bgm_{mood}_{round(duration)}s_{seed}_v{MUSIC_VERSION}.m4a"


def _write_wav(path: Path, mood: str, duration: float, seed: int) -> None:
    samples = synth(mood, duration, seed)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(struct.pack(f"<{len(samples)}h", *(int(x * 32000) for x in samples)))


async def render_bgm(out: Path, mood: str, duration: float, seed: int) -> Path:
    """합성 → WAV → FFmpeg(공간감·페이드·음량 맞춤) → AAC. 같은 파일이 있으면 그대로 쓴다."""
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    wav = out.with_suffix(".tmp.wav")
    await asyncio.to_thread(
        _write_wav, wav, mood, duration, seed
    )  # CPU 몇 초: 이벤트 루프를 막지 않는다
    fade_out = max(0.0, duration - 2.0)
    af = (
        "highpass=f=45,lowpass=f=7500,"
        "aecho=0.8:0.55:70|110:0.22|0.15,"
        f"afade=t=in:d=1.2,afade=t=out:st={fade_out:.2f}:d=2,"
        "loudnorm=I=-18:TP=-2:LRA=11,aresample=44100"
    )
    try:
        await run(
            [
                find_exe("ffmpeg"),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(wav),
                "-t",
                f"{duration:.2f}",
                "-af",
                af,
                "-ac",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(out),
            ]
        )
    finally:
        wav.unlink(missing_ok=True)
    return out


assert set(get_args(MoodName)) == set(MOOD_LABEL) == set(MOODS)


def timeline_seconds(timeline: Timeline) -> float:
    return sum(s.duration if isinstance(s.duration, float) else 3.0 for s in timeline.scenes)


async def ensure_bgm(video: VideoAdapter, project_dir: Path, timeline: Timeline) -> str:
    """timeline.audio(분위기·variant)에 맞는 합성 음악을 만들고 경로를 timeline.audio.bgm에 넣는다.

    seed는 프로젝트 ID와 variant로 정한다: 같은 프로젝트는 다시 실행해도 같은 곡,
    "다른 곡"이면 바뀐다.
    """
    a = timeline.audio
    mood = a.mood if a.mood in MOODS else DEFAULT_MOOD
    seconds = timeline_seconds(timeline) + 0.5
    seed = zlib.crc32(f"{project_dir.name}:{a.variant}".encode())
    out = project_dir / "assets" / "music" / bgm_filename(mood, seconds, seed)
    await video.make_bgm(out, mood, seconds, seed)
    a.mood, a.source = mood, "generated"
    a.bgm = out.relative_to(project_dir).as_posix()
    return a.bgm
