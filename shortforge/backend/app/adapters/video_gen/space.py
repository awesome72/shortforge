"""장면 그림 → 짧은 영상 (D20, 선택). Hugging Face의 공개 ZeroGPU Space를 쓴다.

- 호출당 요금은 없고 Hugging Face의 하루 GPU 한도를 쓴다. 토큰은 없어도 되고, 있으면 함께 보낸다.
- 공개 데모라 그림과 영문 장면 설명이 외부 서버로 올라가고, 운영자가 바꾸거나 내리면 멈출 수 있다.
  그래서 올리기 전에 메타데이터를 지운 임시 JPEG로 바꾸고 파일 이름을 고정한다.
- Gradio HTTP API를 httpx로 쓴다: 업로드 → /call로 event_id → SSE로 결과 → 파일 내려받기.

실측(2026-11-01, Lightricks/ltx-video-distilled, 12~31초): 576×1024는 4·7초 성공, 720×1280은
4초 성공, 7초는 4회 모두 실패(`event: error`). 그래서 길이로 크기를 고르고 7초에서 자른다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.adapters.base import VideoGenAdapter, VideoGenRequest, VideoGenResult
from app.adapters.image.pixabay_video import conform
from app.adapters.video_gen import hf
from app.adapters.video_gen.errors import VideoGenError
from app.media import find_exe

log = logging.getLogger(__name__)

SPACE_ID = "Lightricks/ltx-video-distilled"
BASE = "https://lightricks-ltx-video-distilled.hf.space/gradio_api"
API = "image_to_video"
NEGATIVE = "worst quality, inconsistent motion, blurry, jittery, distorted, text, watermark"
LARGE = (1280, 720)  # (높이, 너비)
SMALL = (1024, 576)
LARGE_MAX_SEC = 4.0
MIN_SECONDS = 1.5
MAX_SECONDS = 7.0  # 더 긴 장면은 마지막 프레임이 멈춘다
REQUEST_TIMEOUT = 60.0
RESULT_TIMEOUT = 240.0  # 시도 하나의 전체 상한. 그동안 프로젝트가 잠겨 있다
DOWNLOAD_TRIES = 3  # 다시 만들면 하루 한도를 또 쓴다
DOWNLOAD_WAIT = 2.0
UA = {"User-Agent": "ShortForge-videogen"}
UPLOAD_NAME = "scene.jpg"  # 원래 파일 이름을 내보내지 않는다

FAILED = (
    "지금 서비스가 붐비거나 오늘 쓸 수 있는 양을 다 썼을 수 있어요. "
    "내일 다시 하거나 설정에서 유료 방식으로 바꿀 수 있어요."
)
STOPPED = "데모 서버가 멈춘 것 같아요. 조금 뒤에 다시 하거나 설정에서 유료 방식으로 바꿀 수 있어요."
OFFLINE = "데모 서버에 연결하지 못했어요. 인터넷을 확인해 주세요."
TOO_LONG = "시간이 너무 오래 걸려 그만뒀어요. 조금 뒤에 다시 해 보세요."
NO_FILE = "만든 영상을 받지 못했어요. 다시 해 보세요."


@dataclass(frozen=True)
class Try:
    height: int
    width: int
    seconds: float


def attempts(seconds: float) -> list[Try]:
    """처음 시도와 다시 시도. 큰 크기가 실패하면 작은 크기로 간다."""
    sec = min(max(seconds, MIN_SECONDS), MAX_SECONDS)
    first = LARGE if sec <= LARGE_MAX_SEC else SMALL
    return [Try(*first, sec), Try(*SMALL, sec)]


class _Retry(Exception):
    """이번 시도만 실패했다. 연결이 끊겼거나 큰 크기가 실패해 다시 하면 나아질 수 있다."""


def _quota_message(text: str) -> str | None:
    lowered = text.lower()
    if "quota" in lowered or "gpu limit" in lowered:
        return "오늘 쓸 수 있는 무료 사용량을 다 썼어요. 내일 다시 해 보세요."
    return None


def _clip_url(payload: str) -> str:
    try:
        video = json.loads(payload)[0]
        url = video["video"]["url"] if "video" in video else video["url"]
    except (ValueError, LookupError, TypeError) as e:
        raise _Retry from e
    # 응답이 시키는 대로 다른 곳에서 내려받지 않는다
    if not str(url).startswith(f"{BASE}/file="):
        raise VideoGenError("영상을 만들지 못했어요. 다시 해 보세요.")
    return str(url)


def _finish(event: str, payload: str, t: Try) -> str:
    if event == "complete":
        return _clip_url(payload)
    message = _quota_message(payload)
    if message:
        raise VideoGenError(message)
    log.warning("Space 오류 응답 (내용 %d자)", len(payload))
    if (t.height, t.width) == SMALL:  # 같은 크기로 또 하면 한도와 시간만 쓴다
        raise VideoGenError(FAILED)
    raise _Retry


class SpaceVideoGen(VideoGenAdapter):
    def __init__(
        self,
        token: str = "",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        conform_fn=conform,
        shrink_fn=None,
    ) -> None:
        self.token = token
        self.transport = transport
        self.conform_fn = conform_fn
        self.shrink_fn = shrink_fn or hf.shrink

    async def generate(self, req: VideoGenRequest) -> VideoGenResult:
        if self.conform_fn is conform:
            find_exe("ffmpeg")
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        clean = req.out_path.with_name(req.out_path.stem + ".send.jpg")
        try:
            await hf.clean_copy(self.shrink_fn, req.image, clean)  # 위치 정보 등을 지운다
            content = await self._make(req, clean)
        finally:
            clean.unlink(missing_ok=True)
        raw = req.out_path.with_name(req.out_path.stem + ".raw.mp4")
        raw.write_bytes(content)
        try:
            await self.conform_fn(raw, req.out_path)
        finally:
            raw.unlink(missing_ok=True)
        return VideoGenResult(req.out_path, f"hf-space:{SPACE_ID}", 0.0)

    async def _make(self, req: VideoGenRequest, clean: Path) -> bytes:
        headers = {**UA, **({"Authorization": f"Bearer {self.token}"} if self.token else {})}
        async with httpx.AsyncClient(
            transport=self.transport, timeout=REQUEST_TIMEOUT, headers=headers
        ) as client:
            path = await self._upload(client, clean)
            for attempt in attempts(req.seconds):
                try:
                    url = await self._attempt(client, req, path, attempt)
                    break
                except _Retry:
                    log.warning("Space 시도 실패: %d×%d", attempt.width, attempt.height)
            else:
                raise VideoGenError(FAILED)
        return await self._download(url)

    async def _download(self, url: str) -> bytes:
        # 공개 파일이라 토큰을 보내지 않는다
        async with httpx.AsyncClient(
            transport=self.transport, timeout=REQUEST_TIMEOUT, headers=UA
        ) as plain:
            for attempt in range(DOWNLOAD_TRIES):
                if attempt:
                    await asyncio.sleep(DOWNLOAD_WAIT)
                try:
                    r = await plain.get(url)
                except httpx.HTTPError:
                    continue
                if r.status_code == 200 and r.content:
                    return r.content
        raise VideoGenError(NO_FILE)

    async def _attempt(
        self, client: httpx.AsyncClient, req: VideoGenRequest, path: str, t: Try
    ) -> str:
        try:
            async with asyncio.timeout(RESULT_TIMEOUT):
                event_id = await self._call(client, req, path, t)
                timeout = httpx.Timeout(REQUEST_TIMEOUT, read=RESULT_TIMEOUT)
                url = f"{BASE}/call/{API}/{event_id}"
                async with client.stream("GET", url, timeout=timeout) as stream:
                    if stream.status_code >= 400:
                        raise _Retry
                    event = ""
                    async for line in stream.aiter_lines():
                        if line.startswith("event:"):
                            event = line[6:].strip()
                        elif line.startswith("data:") and event in ("complete", "error"):
                            # 결과가 오면 바로 끝낸다: 뒤에서 끊겨도 만든 영상을 버리지 않는다
                            return _finish(event, line[5:].strip(), t)
        except TimeoutError as e:
            raise VideoGenError(TOO_LONG) from e
        except (httpx.HTTPError, ValueError) as e:  # 스트림이 끊기는 일이 실제로 있었다
            log.warning("Space 연결 끊김: %s", type(e).__name__)
            raise _Retry from e
        raise _Retry

    async def _call(
        self, client: httpx.AsyncClient, req: VideoGenRequest, path: str, t: Try
    ) -> str:
        r = await client.post(
            f"{BASE}/call/{API}",
            json={
                "data": [
                    hf.motion_prompt(req.prompt),
                    NEGATIVE,
                    {"path": path, "meta": {"_type": "gradio.FileData"}},
                    None,
                    t.height,
                    t.width,
                    "image-to-video",
                    t.seconds,
                    9,  # 이미지 모드에서는 쓰지 않는 값 (API 기본값)
                    req.seed,
                    False,
                    1,
                    True,
                ]
            },
        )
        if r.status_code in (404, 503):
            raise VideoGenError(STOPPED)
        if r.status_code >= 400:
            log.warning("Space 호출 거절: HTTP %d", r.status_code)
            raise _Retry
        body = r.json()
        event_id = body.get("event_id") if isinstance(body, dict) else None
        if not event_id:
            raise _Retry
        return str(event_id)

    async def _upload(self, client: httpx.AsyncClient, clean: Path) -> str:
        files = {"files": (UPLOAD_NAME, clean.read_bytes(), "image/jpeg")}
        try:
            r = await client.post(f"{BASE}/upload", files=files)
        except httpx.ConnectError as e:
            raise VideoGenError(OFFLINE) from e
        except httpx.HTTPError as e:
            raise VideoGenError(FAILED) from e
        if r.status_code in (404, 503):
            raise VideoGenError(STOPPED)
        if r.status_code >= 400:
            raise VideoGenError(FAILED)
        try:
            paths = r.json()
        except ValueError as e:
            raise VideoGenError(FAILED) from e
        if not isinstance(paths, list) or not paths:
            raise VideoGenError(FAILED)
        return str(paths[0])
