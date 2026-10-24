"""FFmpeg 렌더러 통합 테스트. 작은 캔버스로 빠르게 돈다. FFmpeg가 없으면 건너뛴다."""

import json
import subprocess

import pytest

from app.adapters.video.ffmpeg import FFmpegRenderer, _zoompan
from app.media import MediaError, find_exe
from app.schemas.project import Canvas, Caption, Timeline, TimelineScene, Transition

try:
    FFMPEG = find_exe("ffmpeg")
except MediaError:
    FFMPEG = None

pytestmark = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg 없음")


def lavfi(out, *args):
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", *args, str(out)], check=True)


@pytest.fixture
def media(tmp_path):
    for i, color in enumerate(["red", "green", "blue"]):
        lavfi(tmp_path / f"img{i}.png", "-i", f"color=c={color}:s=640x480", "-frames:v", "1")
        lavfi(tmp_path / f"v{i}.mp3", "-i", f"sine=f={300 + 100 * i}:d=1.0")
    (tmp_path / "v0.words.json").write_text(
        json.dumps(
            [{"text": "첫", "start": 0.1, "end": 0.4}, {"text": "장면", "start": 0.5, "end": 0.9}]
        ),
        encoding="utf-8",
    )
    lavfi(tmp_path / "bgm.mp3", "-i", "sine=f=110:d=2")
    return tmp_path


def probe(path):
    out = subprocess.run(
        [find_exe("ffprobe"), "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(out.stdout)


def timeline(bgm=None):
    transitions = [Transition(type="cut", dur=0), Transition(type="fade"), Transition(type="slide")]
    return Timeline(
        canvas=Canvas(w=270, h=480, fps=15),
        scenes=[
            TimelineScene(
                id=f"S{i + 1}",
                image=f"img{i}.png",
                voice=f"v{i}.mp3",
                duration=1.2,
                transition=transitions[i],
                caption=Caption(text=f"장면 {i + 1}", style="hook_bold" if i == 0 else "body"),
            )
            for i in range(3)
        ],
        audio={"bgm": bgm},
    )


async def test_render_produces_mp4_srt_and_log(media):
    events = []

    async def progress(stage, frac):
        events.append((stage, frac))

    r = FFmpegRenderer(preset="ultrafast", workers=2)
    result = await r.render(timeline(bgm="bgm.mp3"), media, progress)

    info = probe(result.path)
    kinds = {s["codec_type"]: s for s in info["streams"]}
    assert kinds["video"]["width"] == 270 and kinds["video"]["height"] == 480
    assert "audio" in kinds
    assert float(info["format"]["duration"]) == pytest.approx(3.6, abs=0.15)
    assert result.duration_sec == pytest.approx(3.6)

    srt = result.srt.read_text(encoding="utf-8")
    assert "첫 장면" in srt  # S1은 단어 타이밍
    assert "00:00:02,400 -->" in srt  # S3 자막은 S3 시작(2.4초)에 맞춰 밀린다
    assert "[timing] total" in result.log.read_text(encoding="utf-8")
    assert ("clips", 1.0) in events and any(s == "compose" for s, _ in events)


async def test_rerender_reuses_unchanged_clips(media):
    """자막만 바꿔 다시 렌더하면 클립을 다시 만들지 않고, 모션을 바꾼 장면만 새로 만든다."""

    async def noop(*a):
        pass

    r = FFmpegRenderer(preset="ultrafast", workers=2)
    tl = timeline()
    first = await r.render(tl, media, noop)
    work = media / "render" / "work"
    clips1 = sorted(work.glob("clip_*.mp4"))
    assert len(clips1) == 3

    tl.scenes[0].caption.text = "자막만 바꿨다"
    await r.render(tl, media, noop)
    log = first.log.read_text(encoding="utf-8")
    assert log.count("재사용") == 3
    assert sorted(work.glob("clip_*.mp4")) == clips1

    tl.scenes[1].motion.type = "zoom_out" if tl.scenes[1].motion.type != "zoom_out" else "zoom_in"
    await r.render(tl, media, noop)
    clips3 = sorted(work.glob("clip_*.mp4"))
    assert len(clips3) == 3  # 쓰지 않게 된 예전 클립은 지운다
    assert len(set(clips3) & set(clips1)) == 2
    assert not list(work.glob("*.part.mp4"))


async def test_missing_file_raises(media):
    tl = timeline()
    tl.scenes[1].image = "nope.png"
    with pytest.raises(FileNotFoundError, match="S2"):
        await FFmpegRenderer().render(tl, media, lambda *a: None)


@pytest.mark.parametrize("kind", ["zoom_in", "zoom_out", "pan_left", "pan_right", "static"])
def test_zoompan_expressions(kind):
    expr = _zoompan(kind, 0.12, 90, 1080, 1920, 30)
    assert expr.startswith("zoompan=") and "d=90" in expr and "s=1080x1920" in expr


def video_seconds(path):
    out = subprocess.run(
        [find_exe("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(out.stdout.strip())


async def test_cut_transitions_keep_video_to_the_end(media):
    """컷(1프레임 전환)이 이어져도 화면이 끝까지 나온다.

    2026-10-24: 클립 프레임 수를 반올림하던 탓에 앞 클립이 한 프레임 모자라 xfade가 그 자리에서
    영상을 끊었다(32초 영상의 화면이 17초에서 끝남). 어색한 소수 길이 + 컷 연속으로 재현한다.
    """

    async def noop(*a):
        pass

    tl = timeline()
    for sc, d in zip(tl.scenes, (1.29, 1.22, 1.41), strict=True):
        sc.duration = d
        sc.transition = Transition(type="cut", dur=0.3)
    r = FFmpegRenderer(preset="ultrafast", workers=2, grade="off")
    result = await r.render(tl, media, noop)
    assert video_seconds(result.path) == pytest.approx(1.29 + 1.22 + 1.41, abs=0.1)


async def test_film_grade_and_end_fade_in_graph(media):
    async def noop(*a):
        pass

    r = FFmpegRenderer(preset="ultrafast", workers=2, grade="film")
    result = await r.render(timeline(), media, noop)
    graph = (media / "render" / "work" / "graph.txt").read_text(encoding="utf-8")
    # 무거운 보정(대비·톤·비네팅)은 병렬·캐시되는 장면 클립 단계, 그레인·끝 페이드만 합성 단계
    assert "vignette" in r.clip_grade and "colorbalance" not in r.clip_grade
    assert "noise=" in graph and "fade=t=out" in graph and "afade=t=out" in graph
    assert "vignette" not in graph
    assert video_seconds(result.path) == pytest.approx(3.6, abs=0.15)
