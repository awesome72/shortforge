"""내보내기 전 자동 점검 (S7)과 렌더 방식 버전. FFmpeg 없이 돈다."""

from pathlib import Path

from app.adapters.base import RenderResult
from app.adapters.video.ffmpeg import parse_loudness, parse_silences
from app.schemas.project import Render
from app.steps.s7_render import RENDER_QUALITY, render_checks, rendered_quality
from app.subtitles import Cue, too_wide, wrap_title

EBUR128 = """[Parsed_ebur128_1 @ 0x1] Summary:

  Integrated loudness:
    I:         -14.2 LUFS
    Threshold: -24.3 LUFS
"""


def result(**kw) -> RenderResult:
    p = Path("x")
    return RenderResult(path=p, srt=p, duration_sec=kw.pop("duration", 30.0), log=p, **kw)


def test_parse_loudness_takes_summary():
    assert parse_loudness("t: 1.0  M: -20.1 S: -21.0 I: -19.0 LUFS\n" + EBUR128) == -14.2
    assert parse_loudness("no audio") is None


def test_parse_silences_pairs_and_open_end():
    err = (
        "[silencedetect @ 0x1] silence_start: 12.5\n"
        "[silencedetect @ 0x1] silence_end: 14.25 | silence_duration: 1.75\n"
        "[silencedetect @ 0x1] silence_start: 29.2\n"
    )
    assert parse_silences(err, 30.0) == [(12.5, 1.75), (29.2, 0.8)]


def test_checks_pass_for_a_clean_render():
    checks = render_checks(result(loudness_lufs=-14.1), 30)
    assert [c.id for c in checks] == ["duration", "loudness", "silence", "caption_width"]
    assert all(c.ok for c in checks)


def test_checks_flag_problems():
    r = result(
        duration=36.0,
        loudness_lufs=-19.0,
        silences=[(0.0, 0.3), (10.0, 2.0), (35.6, 0.4)],  # 처음·끝 페이드는 빼고 본다
        wide_captions=["아주 긴 자막이 화면을 넘어간다"],
    )
    bad = {c.id: c.detail for c in render_checks(r, 30) if not c.ok}
    assert set(bad) == {"duration", "loudness", "silence", "caption_width"}
    assert "+20%" in bad["duration"]
    assert "10.0초부터 2.0초" in bad["silence"]


def test_unmeasured_items_are_left_out():
    ids = [c.id for c in render_checks(result(duration=0.0), 30)]
    assert ids == ["silence", "caption_width"]  # 길이 0(가짜 렌더)·음량 없음은 판정하지 않는다


def test_rendered_quality_guesses_old_renders(tmp_path):
    r = Render(path="render/final.mp4", srt="render/final.srt", duration_sec=30, log="l")
    assert rendered_quality(tmp_path, r) == 1  # 자막 파일도 없음
    work = tmp_path / "render" / "work"
    work.mkdir(parents=True)
    (work / "subs.ass").write_text(r"Style: body,x" + "\n" + r"{\blur1.5}", encoding="utf-8")
    assert rendered_quality(tmp_path, r) == 2
    (work / "subs.ass").write_text("Style: dim,x", encoding="utf-8")
    assert rendered_quality(tmp_path, r) == 3
    r.quality = RENDER_QUALITY
    assert rendered_quality(tmp_path, r) == RENDER_QUALITY


def test_too_wide_estimates_korean_width():
    cues = [
        Cue(0, 1, "은퇴 끝이 아니에요", "hook_bold"),
        Cue(1, 2, "하루 십 분이면 충분한 이유를 알려드릴게요", "body"),
        Cue(2, 3, "짧은 줄\n두 번째 줄", "body"),
    ]
    assert too_wide(cues, 1080) == ["하루 십 분이면 충분한 이유를 알려드릴게요"]


def test_cover_title_breaks_between_meaning_units():
    lines = wrap_title("은퇴 후 30년, 나만의 두 번째 인생 지도 그리는 법").split("\n")
    assert lines[0] == "은퇴 후 30년,"  # 쉼표에서 끊는다
    assert not any(line.endswith(" 두") for line in lines)  # "두 / 번째"로 가르지 않는다
    assert all(len(line) <= 10 for line in lines)


def test_cover_title_slash_is_a_manual_line_break():
    assert wrap_title("퇴근 후 / 10분이면 돼요") == "퇴근 후\n10분이면 돼요"
