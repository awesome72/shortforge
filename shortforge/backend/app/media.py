"""FFmpeg/ffprobe 실행 도구."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Awaitable, Callable
from functools import cache
from pathlib import Path


class MediaError(RuntimeError):
    kind = "media"


class RenderStalled(MediaError):
    kind = "render_stall"


class ToolMissing(MediaError):
    kind = "tool_missing"


# 장면 소스로 쓸 수 있는 동영상 (본인 영상·무료 동영상). 렌더는 확장자로 사진과 구분한다
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}


def is_video_path(path: str | Path | None) -> bool:
    return bool(path) and Path(str(path)).suffix.lower() in VIDEO_EXT


@cache
def find_exe(name: str) -> str:
    """PATH → winget 링크 폴더 순서로 찾는다 (winget 설치 직후엔 PATH가 갱신되지 않은 셸이 많다)."""
    found = shutil.which(name)
    if found:
        return found
    links = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"
    candidate = links / f"{name}.exe"
    if candidate.exists():
        return str(candidate)
    raise ToolMissing(f"{name}을 찾을 수 없다 — FFmpeg를 설치한다 (winget install Gyan.FFmpeg)")


async def replace_file(part: Path, final: Path, failed: str, tries: int = 10) -> None:
    """임시 파일을 제자리로. Windows에서는 재생·백신이 파일을 잠깐 잡고 있을 수 있다."""
    for attempt in range(tries):
        try:
            os.replace(part, final)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise MediaError(failed) from None
            await asyncio.sleep(0.5)


# 한 번의 FFmpeg 실행 상한. 30초 영상의 합성도 1~5분이라 넉넉하다. 합성은 따로 멈춤 감시가 있고,
# 장면 클립·무료 영상 변환·음악 합성은 멈추면 끝없이 기다렸다(코드 리뷰 2026-11-07)
DEFAULT_TIMEOUT_SEC = 1800.0


async def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    on_line: Callable[[str], Awaitable[None]] | None = None,
    low_priority: bool = False,
    should_stop: Callable[[], bool] | None = None,
    timeout: float | None = DEFAULT_TIMEOUT_SEC,
) -> str:
    """명령을 실행하고 stderr를 돌려준다. 실패하면 MediaError. on_line은 stdout 줄마다 호출.

    asyncio 서브프로세스 대신 스레드에서 subprocess를 돌린다. Windows의 SelectorEventLoop
    (uvicorn --reload가 쓰는 루프)는 asyncio 서브프로세스를 지원하지 않기 때문이다.
    """
    loop = asyncio.get_running_loop()
    # 낮은 우선순위: 다른 프로그램이 쓰지 않는 CPU만 쓴다 (미리 만들기)
    extra: dict = {}
    if low_priority and os.name == "nt":
        extra["creationflags"] = subprocess.IDLE_PRIORITY_CLASS
    elif low_priority:
        extra["preexec_fn"] = lambda: os.nice(19)

    def work() -> tuple[int, bytes]:
        proc = subprocess.Popen(
            args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **extra
        )
        err: list[bytes] = []
        reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
        reader.start()  # stderr를 따로 비워야 파이프가 차서 멈추지 않는다

        started = time.monotonic()

        def watch() -> None:  # 멈추면 종료 코드가 0이 아니라 MediaError가 난다
            while proc.poll() is None:
                if cancelled.is_set() or (should_stop and should_stop()):
                    proc.terminate()
                    return
                if timeout and time.monotonic() - started > timeout:
                    timed_out.set()
                    proc.terminate()
                    return
                time.sleep(0.25)

        threading.Thread(target=watch, daemon=True).start()
        assert proc.stdout
        for raw in proc.stdout:
            if on_line:
                if cancelled.is_set():
                    continue  # 멈춘 작업의 진행 표시는 보내지 않는다 (끝날 때까지 읽어 비운다)
                line = raw.decode("utf-8", "replace").strip()
                asyncio.run_coroutine_threadsafe(on_line(line), loop).result()
        proc.wait()
        reader.join()
        return proc.returncode, b"".join(err)

    cancelled = threading.Event()  # 작업을 멈추면(취소) FFmpeg도 끈다. 스레드는 혼자 계속 돌았다
    timed_out = threading.Event()
    try:
        code, stderr = await asyncio.to_thread(work)
    except asyncio.CancelledError:
        cancelled.set()
        raise
    err_text = stderr.decode("utf-8", "replace")
    if timed_out.is_set():
        raise MediaError(f"{Path(args[0]).stem} 실행이 {timeout:.0f}초 안에 끝나지 않아 멈췄어요")
    if code != 0:
        tail = "\n".join(err_text.strip().splitlines()[-15:])
        raise MediaError(f"{Path(args[0]).stem} 실패 (exit {code}):\n{tail}")
    return err_text


async def probe_duration(path: Path) -> float:
    def work() -> subprocess.CompletedProcess:
        return subprocess.run(
            [find_exe("ffprobe"), "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True,
        )  # fmt: skip

    out = await asyncio.to_thread(work)
    if out.returncode != 0:
        raise MediaError(f"ffprobe 실패: {path}: {out.stderr.decode('utf-8', 'replace').strip()}")
    return float(json.loads(out.stdout)["format"]["duration"])


async def probe_size(path: Path) -> tuple[int, int] | None:
    """화면에 보이는 (너비, 높이). 읽지 못하면 None (렌더는 예전처럼 잘라 채운다).

    휴대폰 세로 사진은 가로 픽셀에 EXIF 회전값을 붙여 저장되고 FFmpeg는 돌려서 읽는다.
    저장된 크기만 보면 세로 사진이 가로로 잡혀 흐린 배경 맞춤에 걸렸다(검토에서 재현).
    """

    def work() -> subprocess.CompletedProcess:
        return subprocess.run(
            [find_exe("ffprobe"), "-v", "error", "-select_streams", "v:0",
             "-read_intervals", "%+#1", "-show_frames",
             "-show_entries", "frame=width,height:frame_side_data=rotation",
             "-of", "json", str(path)],
            capture_output=True,
        )  # fmt: skip

    try:
        out = await asyncio.to_thread(work)
        frame = json.loads(out.stdout)["frames"][0]
        w, h = int(frame["width"]), int(frame["height"])
        rotation = next(
            (int(d["rotation"]) for d in frame.get("side_data_list", []) if "rotation" in d), 0
        )
        return (h, w) if abs(rotation) % 180 == 90 else (w, h)
    except (OSError, ValueError, LookupError, TypeError):
        return None


def available_memory_mb() -> int | None:
    """지금 남은 물리 메모리(MB). 알 수 없으면 None."""
    try:
        if os.name == "nt":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            st = MemoryStatus()
            st.dwLength = ctypes.sizeof(MemoryStatus)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return None
            return int(st.ullAvailPhys // 1_048_576)
        return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // 1_048_576)
    except (OSError, ValueError, AttributeError):
        return None
