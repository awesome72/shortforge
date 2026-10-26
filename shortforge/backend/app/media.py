"""FFmpeg/ffprobe 실행 도구."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
from collections.abc import Awaitable, Callable
from functools import cache
from pathlib import Path


class MediaError(RuntimeError):
    pass


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
    raise MediaError(f"{name}을 찾을 수 없다 — FFmpeg를 설치한다 (winget install Gyan.FFmpeg)")


async def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    on_line: Callable[[str], Awaitable[None]] | None = None,
) -> str:
    """명령을 실행하고 stderr를 돌려준다. 실패하면 MediaError. on_line은 stdout 줄마다 호출.

    asyncio 서브프로세스 대신 스레드에서 subprocess를 돌린다. Windows의 SelectorEventLoop
    (uvicorn --reload가 쓰는 루프)는 asyncio 서브프로세스를 지원하지 않기 때문이다.
    """
    loop = asyncio.get_running_loop()

    def work() -> tuple[int, bytes]:
        proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        err: list[bytes] = []
        reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
        reader.start()  # stderr를 따로 비워야 파이프가 차서 멈추지 않는다
        assert proc.stdout
        for raw in proc.stdout:
            if on_line:
                line = raw.decode("utf-8", "replace").strip()
                asyncio.run_coroutine_threadsafe(on_line(line), loop).result()
        proc.wait()
        reader.join()
        return proc.returncode, b"".join(err)

    code, stderr = await asyncio.to_thread(work)
    err_text = stderr.decode("utf-8", "replace")
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
