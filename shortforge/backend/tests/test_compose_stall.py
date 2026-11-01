"""합성이 멈춰도 지난 완성본을 망가뜨리지 않고 다시 시도한다 (FFmpeg 없이)."""

import asyncio
from pathlib import Path

import pytest

import app.adapters.video.ffmpeg as ff
from app.media import MediaError


class Log:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)


async def _progress(stage, value):
    return None


@pytest.fixture
def paths(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-good-video")
    return tmp_path / "final.part.mp4", final, tmp_path


def fake_run(part, plans):
    """plans의 각 항목은 그 시도의 동작: ok, stall(진행이 멈춘 뒤 꺼짐), broken(FFmpeg 오류)."""
    calls = []

    async def run(args, cwd=None, on_line=None, should_stop=None):
        step = plans[len(calls)]
        calls.append(step)
        await on_line("out_time_us=1000000")
        part.write_bytes(b"partial")
        if step == "ok":
            part.write_bytes(b"new-video")
            return ""
        if step == "stall":
            ff.COMPOSE_STALL_SEC = -1  # 시계를 기다리지 않고 멈춘 상태로 만든다
            assert should_stop() is True
            raise MediaError("terminated")
        raise MediaError("ffmpeg error")

    return run, calls


@pytest.fixture(autouse=True)
def _restore_stall(monkeypatch):
    monkeypatch.setattr(ff, "COMPOSE_STALL_SEC", ff.COMPOSE_STALL_SEC)


async def test_success_replaces_the_final_video(paths, monkeypatch):
    part, final, cwd = paths
    run, _ = fake_run(part, ["ok"])
    monkeypatch.setattr(ff, "run", run)
    await ff._encode(["ffmpeg"], part, final, 30.0, cwd, Log(), _progress)
    assert final.read_bytes() == b"new-video"
    assert not part.exists()


async def test_stall_keeps_the_old_video_and_retries(paths, monkeypatch):
    part, final, cwd = paths
    run, calls = fake_run(part, ["stall", "ok"])

    async def run_then_reset(*args, **kwargs):
        try:
            return await run(*args, **kwargs)
        finally:
            if len(calls) == 1:
                assert final.read_bytes() == b"old-good-video"

    monkeypatch.setattr(ff, "run", run_then_reset)
    log = Log()
    await ff._encode(["ffmpeg"], part, final, 30.0, cwd, log, _progress)
    assert calls == ["stall", "ok"]
    assert final.read_bytes() == b"new-video"
    assert any("멈춤" in line for line in log.lines)


async def test_stalling_twice_gives_up_without_touching_the_old_video(paths, monkeypatch):
    part, final, cwd = paths
    run, calls = fake_run(part, ["stall", "stall"])
    monkeypatch.setattr(ff, "run", run)
    with pytest.raises(MediaError, match="멈췄어요"):
        await ff._encode(["ffmpeg"], part, final, 30.0, cwd, Log(), _progress)
    assert len(calls) == 2
    assert final.read_bytes() == b"old-good-video"
    assert not part.exists()


async def test_real_ffmpeg_error_is_not_retried(paths, monkeypatch):
    part, final, cwd = paths
    run, calls = fake_run(part, ["broken", "ok"])
    monkeypatch.setattr(ff, "run", run)
    with pytest.raises(MediaError, match="ffmpeg error"):
        await ff._encode(["ffmpeg"], part, final, 30.0, cwd, Log(), _progress)
    assert len(calls) == 1
    assert final.read_bytes() == b"old-good-video"


async def test_repeating_the_same_time_counts_as_a_stall(paths, monkeypatch):
    # 멈춘 FFmpeg도 진행 줄은 0.5초마다 낸다: 같은 시각이 반복되면 멈춘 것이다
    part, final, cwd = paths
    monkeypatch.setattr(ff, "COMPOSE_STALL_SEC", 0.05)
    lines = []

    async def run(args, cwd=None, on_line=None, should_stop=None):
        while not should_stop():
            await on_line("out_time_us=29000000")
            lines.append(1)
            await asyncio.sleep(0.005)
        raise MediaError("terminated")

    monkeypatch.setattr(ff, "run", run)
    with pytest.raises(MediaError, match="멈췄어요"):
        await ff._encode(["ffmpeg"], part, final, 30.0, cwd, Log(), _progress)
    assert len(lines) > 3
    assert final.read_bytes() == b"old-good-video"


async def test_moving_time_is_never_a_stall(paths, monkeypatch):
    part, final, cwd = paths
    monkeypatch.setattr(ff, "COMPOSE_STALL_SEC", 0.05)

    async def run(args, cwd=None, on_line=None, should_stop=None):
        for us in range(1, 40):
            await on_line(f"out_time_us={us}")
            await asyncio.sleep(0.005)
            assert not should_stop()
        part.write_bytes(b"new-video")
        return ""

    monkeypatch.setattr(ff, "run", run)
    await ff._encode(["ffmpeg"], part, final, 30.0, cwd, Log(), _progress)
    assert final.read_bytes() == b"new-video"


async def test_time_that_moved_just_before_the_stop_still_counts_as_a_stall(paths, monkeypatch):
    # 끄기 직전 버퍼의 진행 줄이 늦게 와도 재시도한다 (FFmpeg 오류로 끝내지 않는다)
    part, final, cwd = paths
    monkeypatch.setattr(ff, "COMPOSE_STALL_SEC", -1)
    calls = []

    async def run(args, cwd=None, on_line=None, should_stop=None):
        calls.append(1)
        if len(calls) == 1:
            assert should_stop() is True
            monkeypatch.setattr(ff, "COMPOSE_STALL_SEC", 1000)
            await on_line("out_time_us=5")
            raise MediaError("terminated")
        part.write_bytes(b"new-video")
        return ""

    monkeypatch.setattr(ff, "run", run)
    await ff._encode(["ffmpeg"], part, final, 30.0, cwd, Log(), _progress)
    assert len(calls) == 2


async def test_locked_part_file_does_not_hide_the_real_error(paths, monkeypatch):
    part, final, cwd = paths
    run, _ = fake_run(part, ["broken"])
    monkeypatch.setattr(ff, "run", run)
    real = Path.unlink

    def locked(self, missing_ok=False):
        if self == part:
            raise PermissionError("locked")
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(MediaError, match="ffmpeg error"):
        await ff._encode(["ffmpeg"], part, final, 30.0, cwd, Log(), _progress)


async def test_playing_file_gets_a_clear_message(paths, monkeypatch):
    part, final, _ = paths
    part.write_bytes(b"new")
    monkeypatch.setattr(ff, "REPLACE_TRIES", 2)

    def locked(a, b):
        raise PermissionError("in use")

    async def no_wait(_):
        return None

    monkeypatch.setattr(ff.os, "replace", locked)
    monkeypatch.setattr(ff.asyncio, "sleep", no_wait)
    with pytest.raises(MediaError, match="재생을 멈추고"):
        await ff._replace(part, final)
