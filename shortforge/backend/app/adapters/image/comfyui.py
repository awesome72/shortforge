"""원격 ComfyUI 이미지 어댑터 (IMAGE_MODE=comfyui, Step 8 · D4).

GPU가 있는 다른 장비(본인 PC·서버)에서 ComfyUI를 띄워 두고 그 HTTP API를 쓴다 — 비용 ₩0 유지.
흐름: POST /prompt(워크플로 제출) → GET /history/{id} 폴링 → GET /view로 이미지 받기.

워크플로는 ComfyUI의 "Save (API Format)" JSON이다. 문자열 값의 {{prompt}} {{negative}} {{seed}}
{{width}} {{height}} 자리표시자를 채운다. 값 전체가 자리표시자면 숫자는 숫자로 넣는다.
기본 템플릿(workflows/sdxl_txt2img.json)은 SDXL 체크포인트용이다.
FLUX.1 schnell 등은 자기 워크플로를 COMFYUI_WORKFLOW로 지정한다.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.adapters.base import ImageAdapter

DEFAULT_WORKFLOW = Path(__file__).parent / "workflows" / "sdxl_txt2img.json"
POLL_SEC = 1.0
TIMEOUT_SEC = 300
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class ComfyUIError(RuntimeError):
    pass


def fill_workflow(workflow: dict, values: dict[str, Any]) -> dict:
    """워크플로 JSON의 자리표시자를 채운 사본을 돌려준다."""

    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, str):
            whole = PLACEHOLDER.fullmatch(node)
            if whole and whole.group(1) in values:
                return values[whole.group(1)]  # 숫자 자리는 숫자 그대로
            return PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), node)
        return node

    return walk(copy.deepcopy(workflow))


class ComfyUIAdapter(ImageAdapter):
    def __init__(
        self,
        base_url: str,
        *,
        workflow_path: Path | None = None,
        width: int = 768,
        height: int = 1344,  # 9:16에 가까운 SDXL 해상도. 렌더러가 1080×1920으로 맞춘다
        poll_sec: float = POLL_SEC,
        timeout_sec: float = TIMEOUT_SEC,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ComfyUIError("COMFYUI_URL이 비어 있다 — 예: http://192.168.0.20:8188")
        path = workflow_path or DEFAULT_WORKFLOW
        self.workflow = json.loads(Path(path).read_text(encoding="utf-8"))
        self.width, self.height = width, height
        self.poll_sec, self.timeout_sec = poll_sec, timeout_sec
        self.client_id = uuid.uuid4().hex
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=30, transport=transport
        )

    async def generate(self, prompt: str, negative: str, seed: int, out_path: Path) -> Path:
        wf = fill_workflow(
            self.workflow,
            {"prompt": prompt, "negative": negative, "seed": seed,
             "width": self.width, "height": self.height},
        )  # fmt: skip
        try:
            r = await self.client.post("/prompt", json={"prompt": wf, "client_id": self.client_id})
        except httpx.TransportError as e:
            raise ComfyUIError(f"ComfyUI에 연결할 수 없다 ({self.client.base_url}): {e}") from e
        if r.status_code != 200:
            raise ComfyUIError(f"워크플로 제출 실패 HTTP {r.status_code}: {r.text[:300]}")
        prompt_id = r.json()["prompt_id"]

        image = await self._wait(prompt_id)
        data = await self.client.get("/view", params=image)
        data.raise_for_status()
        out = out_path.with_suffix(Path(image["filename"]).suffix or ".png")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data.content)
        return out

    async def _wait(self, prompt_id: str) -> dict:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_sec
        while loop.time() < deadline:
            r = await self.client.get(f"/history/{prompt_id}")
            entry = r.json().get(prompt_id) if r.status_code == 200 else None
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyUIError(f"ComfyUI 실행 오류: {json.dumps(status)[:300]}")
                for node in entry.get("outputs", {}).values():
                    for img in node.get("images", []):
                        if img.get("type", "output") == "output":
                            sub = img.get("subfolder", "")
                            return {"filename": img["filename"], "subfolder": sub, "type": "output"}
                if status.get("completed"):
                    raise ComfyUIError(
                        "실행은 끝났지만 출력 이미지가 없다 — SaveImage 노드를 확인한다"
                    )
            await asyncio.sleep(self.poll_sec)
        raise ComfyUIError(f"{self.timeout_sec:g}초 안에 이미지가 나오지 않았다")
