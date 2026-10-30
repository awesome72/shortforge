"""회귀: Windows SelectorEventLoop(uvicorn --reload가 쓰는 루프)에서도 FFmpeg 실행이 돼야 한다.

asyncio 서브프로세스는 이 루프에서 NotImplementedError를 낸다 — 웹 UI에서 S5가 이렇게 실패했다.
"""

import asyncio
import subprocess

import pytest

from app.media import MediaError, find_exe, probe_duration, run

try:
    FFMPEG = find_exe("ffmpeg")
except MediaError:
    FFMPEG = None

pytestmark = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg 없음")


def test_probe_and_run_work_on_selector_loop(tmp_path):
    mp3 = tmp_path / "a.mp3"
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=0.5", str(mp3)],
        check=True,
    )
    lines: list[str] = []

    async def collect(line: str) -> None:
        lines.append(line)

    async def main():
        d = await probe_duration(mp3)
        await run([FFMPEG, "-hide_banner", "-version"])
        await run([FFMPEG, "-y", "-loglevel", "error", "-progress", "pipe:1", "-i", str(mp3),
                   "-f", "null", "-"], on_line=collect)  # fmt: skip
        with pytest.raises(MediaError, match="exit"):
            await run([FFMPEG, "-loglevel", "error", "-i", str(tmp_path / "none.mp3")])
        return d

    loop = asyncio.SelectorEventLoop()
    try:
        duration = loop.run_until_complete(main())
    finally:
        loop.close()
    assert duration == pytest.approx(0.5, abs=0.1)
    assert any(line.startswith("out_time") for line in lines)


async def test_run_can_stop_a_running_process():
    import sys
    import time

    from app.media import MediaError, run

    stop = []
    t0 = time.perf_counter()

    async def later():
        await asyncio.sleep(0.2)
        stop.append(1)

    task = asyncio.create_task(later())
    with pytest.raises(MediaError):
        await run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            should_stop=lambda: bool(stop),
            low_priority=True,
        )
    await task
    assert time.perf_counter() - t0 < 10
