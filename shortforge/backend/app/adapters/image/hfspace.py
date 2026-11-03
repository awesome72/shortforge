"""Hugging Face 공개 Space 이미지 어댑터 (IMAGE_MODE의 hfspace, D22).

Cloudflare 무료 한도가 바닥나거나 실패하면 체인이 이 소스로 넘긴다. FLUX.1 [schnell]
(Apache 2.0) 데모 Space를 Gradio HTTP API로 부른다: /call로 event_id → SSE로 결과 → 파일 내려받기.

- 호출당 요금은 없고 하루 ZeroGPU 무료 한도를 쓴다. **토큰은 보내지 않는다:** HF_TOKEN은 영상
  만들기(D19·D20)용으로 받았고 유료 권한이 있을 수 있어, 동의 없이 다른 Space에 넘기지 않는다.
  토큰 없이 3장 연속 성공(2026-11-03, 장당 약 6초). 영상 만들기와 계정 한도를 나눠 쓰지 않는다.
- 사진은 보내지 않는다. 영문 장면 프롬프트만 보낸다(Cloudflare와 같다).
- 데모라 운영자가 바꾸거나 내리면 멈출 수 있다. 그때는 체인이 다음 소스로 넘어간다.

실측(2026-11-03): 864×1536 13장 모두 성공, 장당 6~13초.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.adapters.base import ImageAdapter, ImageQuotaExceeded, ImageRequest, ImageResult

log = logging.getLogger(__name__)

SPACE_ID = "black-forest-labs/FLUX.1-schnell"
BASE = "https://black-forest-labs-flux-1-schnell.hf.space/gradio_api"
API = "infer"
STEPS = 4
RESULT_TIMEOUT = 120.0
UA = {"User-Agent": "ShortForge-image"}


class HFSpaceImageError(RuntimeError):
    pass


def _is_quota(text: str) -> bool:
    lowered = text.lower()  # 입력 검증 오류("maximum … exceeded")를 한도로 보지 않게 좁힌다
    return "quota" in lowered or "gpu limit" in lowered or "zerogpu" in lowered


class HFSpaceImageAdapter(ImageAdapter):
    wants_english_prompts = True

    def __init__(
        self,
        *,
        width: int = 864,
        height: int = 1536,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.width, self.height = width, height
        self.transport = transport

    @property
    def provider(self) -> str:
        return "hfspace:" + SPACE_ID.rsplit("/", 1)[-1]

    async def generate(self, req: ImageRequest) -> ImageResult:
        try:
            async with httpx.AsyncClient(timeout=60, transport=self.transport, headers=UA) as c:
                r = await c.post(
                    f"{BASE}/call/{API}",
                    json={
                        "data": [req.prompt[:2000], req.seed, False, self.width, self.height, STEPS]
                    },
                )
                if r.status_code == 429:
                    raise ImageQuotaExceeded("Hugging Face 무료 GPU 한도 초과")
                if r.status_code >= 400:
                    raise HFSpaceImageError(f"Space 호출 거절 HTTP {r.status_code}")
                event_id = (r.json() or {}).get("event_id")
                if not event_id:
                    raise HFSpaceImageError("Space 응답에 작업 번호가 없다")
                url = await self._result(c, str(event_id))
            async with httpx.AsyncClient(timeout=60, transport=self.transport, headers=UA) as d:
                got = await d.get(url)
        except httpx.TimeoutException as e:
            raise HFSpaceImageError("Space 응답이 너무 늦다") from e
        except httpx.TransportError as e:
            raise HFSpaceImageError(f"Space에 연결할 수 없다: {type(e).__name__}") from e
        if got.status_code != 200 or not got.content:
            raise HFSpaceImageError(f"만든 그림을 받지 못했다 HTTP {got.status_code}")
        data = got.content
        ext = (
            ".png"
            if data.startswith(b"\x89PNG")
            else ".webp"
            if data[:4] == b"RIFF" and data[8:12] == b"WEBP"
            else ".jpg"
            if data.startswith(b"\xff\xd8")
            else ""
        )
        if not ext:
            raise HFSpaceImageError("받은 파일이 그림이 아니다")
        out = req.out_path.with_suffix(ext)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return ImageResult(path=out, source="generated", provider=self.provider)

    async def _result(self, c: httpx.AsyncClient, event_id: str) -> str:
        event = ""
        async with c.stream(
            "GET", f"{BASE}/call/{API}/{event_id}", timeout=RESULT_TIMEOUT
        ) as stream:
            async for line in stream.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event in ("complete", "error"):
                    payload = line[5:].strip()
                    if event == "error":
                        if _is_quota(payload):
                            raise ImageQuotaExceeded("Hugging Face 무료 GPU 한도 초과")
                        log.warning("Space 오류 응답 (내용 %d자)", len(payload))
                        raise HFSpaceImageError("Space가 그림을 만들지 못했다")
                    return _image_url(payload)
        raise HFSpaceImageError("Space 응답이 중간에 끊겼다")


def _image_url(payload: str) -> str:
    try:
        item = json.loads(payload)[0]
        url = item["url"] if isinstance(item, dict) else None
    except (ValueError, LookupError, TypeError) as e:
        raise HFSpaceImageError("Space 응답 형식이 다르다") from e
    # 응답이 시키는 대로 다른 곳에서 내려받지 않는다
    if not isinstance(url, str) or not url.startswith(f"{BASE}/file="):
        raise HFSpaceImageError("Space가 알 수 없는 주소를 돌려줬다")
    return url
