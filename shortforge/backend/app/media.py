"""FFmpeg/ffprobe 실행 도구."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from functools import cache
from pathlib import Path


class MediaError(RuntimeError):
    pass


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
    """명령을 실행하고 stderr를 돌려준다. 실패하면 MediaError. on_line은 stdout 줄마다 호출."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def pump_stdout() -> None:
        assert proc.stdout
        async for raw in proc.stdout:
            if on_line:
                await on_line(raw.decode("utf-8", "replace").strip())

    _, stderr = await asyncio.gather(pump_stdout(), proc.stderr.read())
    await proc.wait()
    err = stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        tail = "\n".join(err.strip().splitlines()[-15:])
        raise MediaError(f"{Path(args[0]).stem} 실패 (exit {proc.returncode}):\n{tail}")
    return err


async def probe_duration(path: Path) -> float:
    out = await asyncio.create_subprocess_exec(
        find_exe("ffprobe"),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    stdout, stderr = await out.communicate()
    if out.returncode != 0:
        raise MediaError(f"ffprobe 실패: {path}: {stderr.decode('utf-8', 'replace').strip()}")
    return float(json.loads(stdout)["format"]["duration"])
