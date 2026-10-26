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
    # 내보내기 전 점검: 완성 영상의 음량을 잰다 (짧은 사인파라 기준과 조금 다를 수 있다)
    assert result.loudness_lufs is not None and -22 < result.loudness_lufs < -10


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


async def test_badges_and_end_card_only_on_screen(media):
    """순서로 시작하는 장면의 번호 배지와 채널 이름 엔딩 카드는 화면(ASS)에만 있고 SRT에는 없다."""

    async def noop(*a):
        pass

    tl = timeline()
    tl.scenes[1].caption.text = "첫째, 기록하기"
    tl.scenes[2].caption.text = "둘째, 이어 가기"
    r = FFmpegRenderer(preset="ultrafast", workers=2, grade="off", brand="mychannel")
    result = await r.render(tl, media, noop)
    ass = (media / "render" / "work" / "subs.ass").read_text(encoding="utf-8")
    assert ",badge,,0,0,0,," in ass and "}01" in ass and "}02" in ass
    assert ",brand,,0,0,0,," in ass and "@mychannel" in ass
    assert r"Dialogue: 0," in ass and r",dim,,0,0,0,,{\an7\pos(0,0)\p1" in ass
    srt = result.srt.read_text(encoding="utf-8")
    assert "@mychannel" not in srt and "01" not in srt.split("-->")[-1]
    graph = (media / "render" / "work" / "graph.txt").read_text(encoding="utf-8")
    assert "acompressor" in graph  # 방송용 목소리 처리


def test_low_memory_reduces_parallel_clips(monkeypatch):
    from app.adapters.video import ffmpeg

    r = FFmpegRenderer(preset="ultrafast")
    r.workers = 4
    monkeypatch.setattr(ffmpeg, "available_memory_mb", lambda: 8000)
    assert r._workers_for_memory() == 4
    monkeypatch.setattr(ffmpeg, "available_memory_mb", lambda: 2000)
    assert r._workers_for_memory() == 2
    monkeypatch.setattr(ffmpeg, "available_memory_mb", lambda: 900)
    assert r._workers_for_memory() == 1
    fixed = FFmpegRenderer(preset="ultrafast", workers=3)  # 설정으로 정했으면 그대로
    assert fixed._workers_for_memory() == 3


async def test_cover_image(media):
    """커버: 장면 이미지 + 제목 한 장 (캔버스 크기 JPEG)."""
    r = FFmpegRenderer(preset="ultrafast", workers=1)
    out = await r.make_cover(
        media / "img0.png", "퇴근 후 10분 홈트", media / "render" / "c.jpg", 270, 480, media
    )
    stream = probe(out)["streams"][0]
    assert (stream["width"], stream["height"]) == (270, 480)
    ass = (media / "render" / "work" / "cover.ass").read_text(encoding="utf-8")
    assert ",cover,,0,0,0,," in ass and "10분" in ass


async def test_video_scene_is_cropped_and_frozen_at_the_end(media):
    """동영상 장면: 9:16으로 잘라 쓰고, 장면보다 짧으면 마지막 프레임에서 멈춰 길이를 채운다."""
    lavfi(media / "clip.mp4", "-i", "testsrc=s=640x360:r=25:d=0.5", "-pix_fmt", "yuv420p")

    async def noop(*a):
        pass

    tl = timeline()
    tl.scenes[1].image = "clip.mp4"  # 1.2초 장면에 0.5초 영상
    result = await FFmpegRenderer(preset="ultrafast", workers=2).render(tl, media, noop)
    info = probe(result.path)
    assert float(info["format"]["duration"]) == pytest.approx(3.6, abs=0.15)
    graph = (media / "render" / "render.log").read_text(encoding="utf-8")
    assert "clip S2" in graph
