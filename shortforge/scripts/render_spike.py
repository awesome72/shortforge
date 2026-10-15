"""Step 2 렌더 스파이크: CPU만으로 30초 영상 ≤ 3분인지 측정한다.

실제 경로: S5(Edge-TTS) → S6(규칙 기반 타임라인) → S7(FFmpeg). LLM·YouTube는 Fake (쿼터 0).

사용법 (shortforge/backend에서):
    uv run python ../scripts/render_spike.py                       # 합성 사진 5장
    uv run python ../scripts/render_spike.py --images D:/photos    # 실제 사진 폴더
    uv run python ../scripts/render_spike.py --presets veryfast,medium --no-bgm
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.fake import FakeYouTube  # noqa: E402
from app.adapters.registry import build_adapters  # noqa: E402
from app.adapters.video.ffmpeg import FFmpegRenderer  # noqa: E402
from app.config import Settings  # noqa: E402
from app.media import find_exe  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.schemas.project import Input, StepState  # noqa: E402
from app.store import ProjectStore  # noqa: E402

LINES = [
    ("hook", "3개월 전의 저는, 계단 두 층에도 숨이 찼어요."),
    ("problem", "퇴근하고 나면 너무 지쳐서, 운동은 늘 내일로 미뤘죠."),
    ("method", "그래서 딱 10분만 하기로 했어요. 스쿼트, 플랭크, 런지. 이 세 가지만요."),
    ("payoff", "석 달이 지난 지금은, 아침에 일어나는 게 확실히 가벼워졌어요."),
    ("cta", "오늘 퇴근길에, 딱 10분만 같이 시작해 볼까요?"),
]
BOUNDS = [(0, 2), (2, 8), (8, 17), (17, 24), (24, 30)]
TARGET_SEC = 180


def ffmpeg(*args: str) -> None:
    subprocess.run([find_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def make_photos(out: Path, n: int) -> list[str]:
    """휴대폰 사진 크기(3024×4032)의 합성 이미지. 디테일이 있어야 인코딩 부하가 현실적이다."""
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n):
        p = out / f"photo_{i + 1}.jpg"
        if not p.exists():
            ffmpeg(
                "-f", "lavfi", "-i", f"gradients=s=3024x4032:seed={i + 7}:speed=0",
                "-f", "lavfi", "-i", "nullsrc=s=3024x4032",
                "-filter_complex",
                f"[1:v]geq=lum='128+60*sin(X/{37 + i * 9})*cos(Y/{53 + i * 5})':cb=128:cr=128[tex];"
                "[0:v][tex]blend=all_mode=overlay:all_opacity=0.5,noise=alls=18:allf=u",
                "-frames:v", "1", "-q:v", "3", str(p),
            )  # fmt: skip
        paths.append(str(p))
    return paths


def make_bgm(out: Path) -> Path:
    p = out / "bgm_test.mp3"
    if not p.exists():
        ffmpeg(
            "-f", "lavfi",
            "-i", "aevalsrc='0.2*sin(2*PI*220*t)+0.15*sin(2*PI*277*t)+0.12*sin(2*PI*330*t)':s=48000:d=40",
            "-c:a", "libmp3lame", "-b:a", "128k", str(p),
        )  # fmt: skip
    return p


def probe(path: Path) -> dict:
    out = subprocess.run(
        [find_exe("ffprobe"), "-v", "error", "-show_entries",
         "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(out.stdout)


def contact_sheet(video: Path, out: Path, times: list[float]) -> None:
    """확인용: 지정 시각 프레임을 가로로 이어 붙인다."""
    inputs, labels = [], []
    for i, t in enumerate(times):
        inputs += ["-ss", f"{t:.2f}", "-i", str(video)]
        labels.append(f"[{i}:v]scale=270:480,setsar=1[f{i}]")
    graph = ";".join(labels) + ";" + "".join(f"[f{i}]" for i in range(len(times)))
    graph += f"hstack=inputs={len(times)}"
    ffmpeg(*inputs, "-filter_complex", graph, "-frames:v", "1", str(out))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=Path, help="실제 사진 폴더 (jpg/png 5장 이상)")
    ap.add_argument("--presets", default="veryfast", help="쉼표로 여러 개 → 비교 측정")
    ap.add_argument("--no-bgm", action="store_true")
    args = ap.parse_args()

    data = ROOT / "data" / "spike"
    settings = Settings(data_dir=data)
    if args.images:
        photos = sorted(str(p) for p in args.images.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:5]
    else:
        t = time.perf_counter()
        photos = make_photos(data / "photos", 5)
        print(f"합성 사진 준비: {time.perf_counter() - t:.1f}s")

    store = ProjectStore(data)
    adapters = build_adapters(settings, fake_llm=True)
    adapters.youtube = FakeYouTube()  # 렌더 측정에 YouTube 쿼터를 쓰지 않는다
    orch = Orchestrator(store, adapters, settings)

    p = store.create(Input(topic="퇴근 후 10분 홈트로 3개월간 바뀐 점", audience="30대 직장인", user_media=photos))
    for s in ("s1", "s2", "s3", "s4"):
        p = await orch.run_step(p.id, s)

    strategy = p.strategy.model_copy(deep=True)
    for scene, (role, line), (a, b) in zip(strategy.scenes, LINES, BOUNDS, strict=True):
        scene.role, scene.line, scene.start, scene.end = role, line, a, b
    await orch.edit(p.id, "strategy", strategy)

    t = time.perf_counter()
    p = await orch.run_step(p.id, "s5")
    tts_sec = time.perf_counter() - t
    if p.status["s5"] != StepState.DONE:
        print("S5 실패:", p.errors)
        return 1
    print(f"S5 TTS 5장면: {tts_sec:.1f}s  (음성 길이 {[a.voice.duration_sec for a in p.assets]})")

    p = await orch.run_step(p.id, "s6")
    if p.status["s6"] != StepState.DONE:
        print("S6 실패:", p.errors)
        return 1
    if not args.no_bgm:
        tl = p.timeline.model_copy(deep=True)
        tl.audio.bgm = str(make_bgm(data))
        p = await orch.edit(p.id, "timeline", tl)
    print("S6 경고:", p.warnings.get("s6", []))

    results = []
    for preset in args.presets.split(","):
        renderer = FFmpegRenderer(preset=preset, font=settings.subtitle_font)
        orch.adapters.video = renderer
        t = time.perf_counter()
        p = await orch.run_step(p.id, "s7")
        wall = time.perf_counter() - t
        if p.status["s7"] != StepState.DONE:
            print(f"[{preset}] S7 실패:", p.errors["s7"])
            return 1
        pdir = store.project_dir(p.id)
        final = pdir / p.render.path
        info = probe(final)
        size_mb = int(info["format"]["size"]) / 1e6
        results.append((preset, wall, renderer.last_timings, size_mb))
        print(f"[{preset}] S7 렌더 {wall:.1f}s  단계별 {renderer.last_timings}  {size_mb:.1f}MB")

    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    print(f"\n산출물: {final}")
    print(f"  영상 {v['codec_name']} {v['width']}x{v['height']} {v['r_frame_rate']}fps · "
          f"음성 {a['codec_name']} {a['sample_rate']}Hz · 길이 {float(info['format']['duration']):.2f}s")
    print(f"  자막 {pdir / p.render.srt}")

    starts, acc = [], 0.0
    for sc in p.timeline.scenes:
        starts.append(acc + 0.8)
        acc += sc.duration
    sheet = pdir / "render" / "contact_sheet.png"
    contact_sheet(final, sheet, starts)
    print(f"  프레임 확인 {sheet}")

    best = min(r[1] for r in results)
    total = tts_sec + best
    verdict = "통과" if total <= TARGET_SEC else "미달"
    print(f"\nGate: TTS {tts_sec:.1f}s + 렌더 {best:.1f}s = {total:.1f}s / 목표 {TARGET_SEC}s → {verdict}")
    return 0 if total <= TARGET_SEC else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
