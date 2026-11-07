"""장면 그림 → 짧은 영상 (D19, 선택·유료). Hugging Face Inference Providers의 fal 경로를 쓴다.

- 사용자의 Hugging Face 토큰으로만 호출하고, 비용은 그 계정의 크레딧에서 나간다.
- 장면 그림을 시작 프레임으로 넘겨(이미지→영상) 장면마다 인물이 달라지지 않게 한다.
- 호출 전에 하루 예산을 확인한다. 동시에 눌러도 예산을 넘지 않게 한 번에 한 장면만 만든다.
- 비용은 요청이 접수되는 순간 사용액에 넣고(예약), 공급자가 분명히 거절했을 때만 되돌린다.
  조회가 끊겨도 공급자 쪽에서는 계속 돌아 청구될 수 있어, 예산은 많이 잡는 쪽으로 틀린다.
- 공식 클라이언트(huggingface_hub)의 fal 큐 방식과 같은 순서를 httpx로 쓴다(의존성을 늘리지 않음):
  요청 → request_id·response_url → status 반복 조회 → 결과의 video.url 내려받기.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import math
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.adapters.base import VideoGenAdapter, VideoGenRequest, VideoGenResult
from app.adapters.image.pixabay_video import conform
from app.adapters.video_gen.errors import VideoGenError
from app.media import MediaError, find_exe, run
from app.spend import VIDEO_MODEL, VIDEO_PROVIDER, SpendMeter

log = logging.getLogger(__name__)

ROUTER = "https://router.huggingface.co/fal-ai"
POLL_SEC = 3.0
TIMEOUT_SEC = 600.0  # 대기열이 길 때를 넉넉히 본다
REQUEST_TIMEOUT = 60.0
DOWNLOAD_TIMEOUT = 120.0
REJECTED = (400, 422)  # 공급자가 내용을 보고 거절했다 (결과가 없어 청구되지 않는다)
DOWNLOAD_TRIES = 3  # 이미 돈을 쓴 결과라 잠깐 끊겨도 여러 번 받아 본다
MIN_SECONDS = 1.5
MAX_SECONDS = 8.0  # 장면 대부분이 2~8초다. 더 긴 장면은 마지막 프레임이 멈춘다
UA = {"User-Agent": "ShortForge-videogen"}


def frames_for(seconds: float) -> int:
    """이 모델의 프레임 수는 8k+1이다. 비용을 넘기지 않게 범위를 먼저 자른다."""
    sec = min(max(seconds, MIN_SECONDS), MAX_SECONDS)
    return math.ceil(sec * VIDEO_MODEL.fps / 8) * 8 + 1


# 결과 영상 주소로 받을 수 있는 곳 (fal 저장소, Hugging Face)
# 실제 유료 호출로 확인하기 전이라 fal이 쓰는 저장소(storage.googleapis.com)도 받는다
RESULT_HOSTS = (
    "fal.media", "fal.ai", "fal.run", "huggingface.co", "hf.co", "storage.googleapis.com",
)  # fmt: skip
MAX_RESULT_BYTES = 200 * 1024 * 1024  # 8초 704×1248 영상은 수 MB다


def result_url_ok(url: str) -> bool:
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(
        host == h or host.endswith("." + h) for h in RESULT_HOSTS
    )


def estimate_usd(seconds: float) -> float:
    return frames_for(seconds) * VIDEO_MODEL.usd_per_frame


MOTION = "Subtle natural movement, slow gentle camera drift."


def motion_prompt(prompt: str) -> str:
    base = prompt.rstrip(" .")
    return f"{base}. {MOTION}" if base else MOTION


async def shrink(src: Path, out: Path) -> Path:
    """외부로 보낼 임시 JPEG. 위치 정보 등 메타데이터를 지우고 높이를 1536까지 줄인다."""
    await run(
        [find_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-map_metadata", "-1", "-frames:v", "1", "-vf", "scale=-2:'min(1536,ih)'",
         "-q:v", "3", str(out)],
    )  # fmt: skip
    return out


async def clean_copy(shrink_fn, src: Path, out: Path) -> None:
    try:
        await shrink_fn(src, out)
    except MediaError as e:  # FFmpeg는 호출 전에 확인했으니 그림 파일 문제다
        raise VideoGenError("이 그림 파일을 읽지 못했어요. 다른 그림으로 바꿔 주세요.") from e


async def image_uri(path: Path, shrink_fn) -> str:
    tmp = path.with_name(path.stem + ".send.jpg")
    try:
        await clean_copy(shrink_fn, path, tmp)
        data = base64.b64encode(tmp.read_bytes()).decode()
    finally:
        tmp.unlink(missing_ok=True)
    return f"data:image/jpeg;base64,{data}"


def _detail(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return f"HTTP {r.status_code}"
    detail = body.get("detail") or body.get("error") if isinstance(body, dict) else None
    if isinstance(detail, list):  # fal의 입력 검증 오류
        detail = detail[0].get("msg") if detail and isinstance(detail[0], dict) else None
    return str(detail)[:200] if detail else f"HTTP {r.status_code}"


def _data(r: httpx.Response) -> dict:
    try:
        body = r.json()
    except ValueError as e:
        raise VideoGenError("영상을 만들지 못했어요. 다시 해 보세요.") from e
    return body if isinstance(body, dict) else {}


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    """조회 한 번. 잠깐 끊긴 경우(연결·429·5xx)는 None: 영상은 계속 만들어지고 있다."""
    try:
        r = await client.get(url)
    except httpx.HTTPError:
        return None
    return None if r.status_code == 429 or r.status_code >= 500 else r


def _failure(r: httpx.Response) -> VideoGenError:
    if r.status_code in (401, 403):
        return VideoGenError(
            "Hugging Face 토큰을 쓸 수 없어요. "
            "토큰에 'Make calls to Inference Providers' 권한이 있는지 확인해 주세요. "
            "권한 없이 만들려면 설정 → 영상 만들기에서 '무료 데모 서버'로 바꿔 주세요."
        )
    if r.status_code == 402:
        return VideoGenError(
            "Hugging Face 크레딧이 모자라요. huggingface.co/settings/billing에서 충전한 뒤 "
            "다시 해 보세요."
        )
    if r.status_code == 429:
        return VideoGenError("요청이 많아 잠시 막혔어요. 조금 뒤에 다시 해 보세요.")
    log.warning("영상 만들기 실패: %s", _detail(r))
    if r.status_code in REJECTED:
        return VideoGenError("이 그림으로는 영상을 만들지 못했어요. 다른 그림으로 해 보세요.")
    if r.status_code >= 500:
        return VideoGenError("지금 서비스가 불안정해요. 조금 뒤에 다시 해 보세요.")
    return VideoGenError("지금은 영상을 만들 수 없어요. 조금 뒤에 다시 해 보세요.")


class HFVideoGen(VideoGenAdapter):
    def __init__(
        self,
        token: str,
        spend: SpendMeter,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        conform_fn=conform,
        shrink_fn=None,
        timeout_sec: float = TIMEOUT_SEC,
    ) -> None:
        self.token = token
        self.spend = spend
        self.transport = transport
        self.sleep = sleep
        self.conform_fn = conform_fn
        self.shrink_fn = shrink_fn or shrink
        self.timeout_sec = timeout_sec
        self._lock = asyncio.Lock()

    async def generate(self, req: VideoGenRequest) -> VideoGenResult:
        cost = estimate_usd(req.seconds)
        if self.conform_fn is conform:
            find_exe("ffmpeg")  # 돈을 쓴 뒤에 FFmpeg가 없다는 것을 알면 늦다
        async with self._lock:  # 예산 확인 → 호출 → 기록을 한 덩어리로 (BudgetExceeded는 그대로)
            self.spend.check_cost(cost)
            payload = {
                "image_url": await image_uri(req.image, self.shrink_fn),
                "prompt": motion_prompt(req.prompt),
                "num_frames": frames_for(req.seconds),
                "fps": VIDEO_MODEL.fps,
                "video_size": {"width": VIDEO_MODEL.width, "height": VIDEO_MODEL.height},
                "seed": req.seed,
                "generate_audio": False,  # 목소리·음악은 ShortForge가 넣는다
                "enable_prompt_expansion": False,  # 장면 묘사를 그대로 쓴다
            }
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=REQUEST_TIMEOUT,
                headers={**UA, "Authorization": f"Bearer {self.token}"},
                follow_redirects=True,
            ) as client:
                result = await self._run_queue(client, payload, cost)
            video = result.get("video")
            url = video.get("url") if isinstance(video, dict) else None
            if not url:
                raise VideoGenError("영상을 만들지 못했어요. 다시 해 보세요.")
            content = await self._download(url)
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        raw = req.out_path.with_name(req.out_path.stem + ".raw.mp4")
        raw.write_bytes(content)
        # 변환에 실패하면 받은 원본(돈을 낸 결과)을 남겨 두고 위치를 로그에 남긴다
        # (지우면 되살릴 수 없었다)
        try:
            await self.conform_fn(raw, req.out_path)
        except Exception:
            log.warning("conform failed, paid original kept at %s", raw.name)
            raise
        raw.unlink(missing_ok=True)
        return VideoGenResult(req.out_path, f"hf:{VIDEO_MODEL.hf_id}", cost)

    async def _download(self, url: str) -> bytes:
        # 결과 주소는 공급자 저장소라 토큰을 보내지 않는다. 응답이 가리키는 아무 주소나 받지 않는다
        if not result_url_ok(url):
            log.warning("video result host refused: %s", urlparse(url).hostname)
            raise VideoGenError("영상 주소가 이상해 받지 않았어요. 다시 해 보세요.")
        async with httpx.AsyncClient(
            transport=self.transport, timeout=DOWNLOAD_TIMEOUT, headers=UA, follow_redirects=True
        ) as plain:
            for attempt in range(DOWNLOAD_TRIES):
                if attempt:
                    await self.sleep(POLL_SEC)
                try:
                    r = await plain.get(url)
                except httpx.HTTPError:
                    continue
                if r.status_code == 200:
                    if len(r.content) > MAX_RESULT_BYTES:
                        raise VideoGenError("받은 영상이 너무 커서 쓰지 않았어요.")
                    return r.content
        raise VideoGenError("만든 영상을 받지 못했어요. 인터넷을 확인해 주세요.")

    async def _run_queue(self, client: httpx.AsyncClient, payload: dict, cost: float) -> dict:
        """큐에 넣고 끝날 때까지 기다린다. 접수되면 바로 비용을 잡고 거절될 때만 되돌린다."""
        query = "?_subdomain=queue"
        try:
            r = await client.post(f"{ROUTER}/{VIDEO_MODEL.provider_id}{query}", json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:  # 요청이 가지 않았다
            raise VideoGenError("Hugging Face에 연결하지 못했어요. 인터넷을 확인해 주세요.") from e
        except httpx.HTTPError as e:  # 보낸 뒤 끊겼다: 접수됐을 수 있다
            self._record(cost)
            raise VideoGenError("응답이 끊겼어요. 조금 뒤에 다시 해 보세요.") from e
        if r.status_code >= 400:
            raise _failure(r)
        self._record(cost)
        queued = _data(r)
        response_url = queued.get("response_url")
        if not queued.get("request_id") or not response_url:
            raise VideoGenError("영상을 만들지 못했어요. 다시 해 보세요.")
        # 공식 클라이언트와 같이 응답의 경로를 라우터 주소에 붙인다 (모델 경로가 달라질 수 있다)
        path = urlparse(response_url).path
        result_url = f"{ROUTER}{path}{query}"
        status_url = f"{ROUTER}{path}/status{query}"
        status = queued.get("status")
        deadline = time.monotonic() + self.timeout_sec
        while True:
            if status in ("FAILED", "ERROR", "CANCELLED"):
                self._record(-cost)
                raise VideoGenError("영상을 만들지 못했어요. 다시 해 보세요.")
            if status == "COMPLETED":
                r = await _get(client, result_url)
                if r is not None:
                    break
            elif time.monotonic() <= deadline:
                r = await _get(client, status_url)
                if r is not None:
                    if r.status_code >= 400:
                        raise _failure(r)
                    status = _data(r).get("status")
                    if status == "COMPLETED":
                        continue
            if time.monotonic() > deadline:
                raise VideoGenError("시간이 너무 오래 걸려 그만뒀어요. 조금 뒤에 다시 해 보세요.")
            await self.sleep(POLL_SEC)
        if r.status_code >= 400:
            if r.status_code in REJECTED:
                self._record(-cost)
            raise _failure(r)  # 인증·찾을 수 없음은 이미 만들어져 청구됐을 수 있어 그대로 둔다
        return _data(r)

    def _record(self, cost: float) -> None:
        self.spend.record_usd(VIDEO_PROVIDER, VIDEO_MODEL.hf_id, "scene_motion", 0, 0, cost)


def _lacks_inference(r: httpx.Response) -> bool:
    """세분화 권한 토큰에 호출 권한이 없는가. 2026-10-31 실제 호출이 이런 토큰에서 403이었다."""
    try:
        token = r.json()["auth"]["accessToken"]
    except (ValueError, KeyError, TypeError):
        return False  # 모양을 모르면 막지 않는다
    if token.get("role") != "fineGrained":
        return False
    fine = token.get("fineGrained") or {}
    granted = list(fine.get("global") or [])
    for scope in fine.get("scoped") or []:
        granted += scope.get("permissions") or []
    return not any(str(p).startswith("inference") for p in granted)


async def check_token(
    token: str, transport: httpx.AsyncBaseTransport | None
) -> tuple[bool | None, str]:
    """토큰만 확인한다 (계정 조회, 비용 없음). 크레딧·권한은 첫 호출 때 알 수 있다."""
    async with httpx.AsyncClient(transport=transport, timeout=30.0, headers=UA) as c:
        r = await c.get(
            "https://huggingface.co/api/whoami-v2", headers={"Authorization": f"Bearer {token}"}
        )
    if r.status_code == 200:
        if _lacks_inference(r):
            return (
                True,
                "토큰 유효. 무료 데모 서버에는 쓸 수 있고, 유료 방식에는 권한이 더 필요하다",
            )
        return True, "토큰 유효"
    if r.status_code == 401:
        return False, "토큰이 맞지 않다 — huggingface.co/settings/tokens에서 다시 복사한다"
    return None, f"지금은 토큰을 확인하지 못했다 (HTTP {r.status_code})"
