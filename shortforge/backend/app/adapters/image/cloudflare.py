"""Cloudflare Workers AI 이미지 어댑터 (IMAGE_MODE에 cloudflare, D12).

무료: 계정마다 하루 10,000 Neurons, 00:00 UTC 초기화 (공식 가격 페이지, 2026-10 확인).
- 기본 모델 FLUX.2 klein 4B: multipart 입력으로 width·height(256~1920)·seed를 받는다 → 정확한 9:16,
  같은 seed면 같은 그림. 비용은 512×512 출력 타일당 26.05 Neurons. 기본 864×1536은 720×1280과 같은
  6타일(2×3)이라 비용이 같은 ≈ 156이면서 화소가 44% 많다 (2026-10-21, 하루 약 64장).
  klein 9B(장당 ≈ 1,364)·FLUX.2 dev(20스텝 장당 ≈ 4,500)는 무료 한도로 하루 영상 1편도
  어려워 쓰지 않는다.
- 대안 FLUX.1 schnell: JSON 입력(prompt, steps)만 받는다 — 정사각형 고정, seed 없음. 1장 ≈ 58.
이용 조건: Black Forest Labs 약관(bfl.ai/legal/terms-of-service). 상업 이용 전 확인한다.
"""

from __future__ import annotations

import base64
import math
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from app.adapters.base import ImageAdapter, ImageQuotaExceeded, ImageRequest, ImageResult
from app.db import connect

API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
KLEIN_4B = "@cf/black-forest-labs/flux-2-klein-4b"
SCHNELL = "@cf/black-forest-labs/flux-1-schnell"
FREE_DAILY_NEURONS = 10_000


class CloudflareImageError(RuntimeError):
    pass


def estimate_neurons(model: str, width: int, height: int, steps: int = 4) -> float:
    """공식 가격표 기준 1장 비용 (2026-10)."""
    if "flux-1-schnell" in model:
        return 4 * 4.80 + steps * 9.60  # 1024×1024 고정 = 4타일
    tiles = math.ceil(width / 512) * math.ceil(height / 512)
    return tiles * 26.05  # klein-4b 출력 타일


def utc_today() -> date:
    return datetime.now(UTC).date()


class NeuronMeter:
    """하루 Neurons 사용량을 로컬에 센다.

    Cloudflare가 호출마다 사용량을 돌려주지 않으므로 가격표 기준 추정치다.
    """

    def __init__(self, db_path: Path, daily_limit: int = FREE_DAILY_NEURONS) -> None:
        self.db_path = Path(db_path)
        self.daily_limit = daily_limit
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect(self.db_path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS neuron_log ("
                " id INTEGER PRIMARY KEY, day TEXT NOT NULL, at TEXT NOT NULL,"
                " model TEXT NOT NULL, neurons REAL NOT NULL)"
            )

    def used(self) -> float:
        with connect(self.db_path) as c:
            row = c.execute(
                "SELECT COALESCE(SUM(neurons), 0) FROM neuron_log WHERE day = ?",
                (utc_today().isoformat(),),
            ).fetchone()
        return float(row[0])

    def check(self, neurons: float) -> None:
        used = self.used()
        if used + neurons > self.daily_limit:
            raise ImageQuotaExceeded(
                f"Cloudflare 이미지 무료 한도 {used:,.0f}/{self.daily_limit:,} Neurons — "
                "00:00 UTC(한국 오전 9시)에 초기화된다"
            )

    def record(self, model: str, neurons: float) -> None:
        with connect(self.db_path) as c:
            c.execute(
                "INSERT INTO neuron_log(day, at, model, neurons) VALUES (?, ?, ?, ?)",
                (utc_today().isoformat(), datetime.now(UTC).isoformat(), model, neurons),
            )

    def summary(self) -> dict:
        used = self.used()
        return {"day_utc": utc_today().isoformat(), "used": round(used), "limit": self.daily_limit}


class CloudflareImageAdapter(ImageAdapter):
    wants_english_prompts = True

    def __init__(
        self,
        account_id: str,
        api_token: str,
        meter: NeuronMeter,
        *,
        model: str = KLEIN_4B,
        width: int = 864,
        height: int = 1536,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not account_id or not api_token:
            raise CloudflareImageError(
                "CLOUDFLARE_ACCOUNT_ID·CLOUDFLARE_API_TOKEN이 비어 있다 — "
                "설정 화면(또는 shortforge/.env)에 넣는다"
            )
        self.url = API.format(account=account_id, model=model)
        self.model = model
        self.width, self.height = width, height
        self.meter = meter
        self.client = httpx.AsyncClient(
            timeout=120, transport=transport, headers={"Authorization": f"Bearer {api_token}"}
        )

    @property
    def provider(self) -> str:
        return "cloudflare:" + self.model.rsplit("/", 1)[-1]

    async def generate(self, req: ImageRequest) -> ImageResult:
        cost = estimate_neurons(self.model, self.width, self.height)
        self.meter.check(cost)
        try:
            if "flux-1-schnell" in self.model:
                r = await self.client.post(self.url, json={"prompt": req.prompt[:2048], "steps": 4})
            else:  # FLUX.2 klein은 multipart만 받는다
                fields = {
                    "prompt": req.prompt[:2048],
                    "width": str(self.width),
                    "height": str(self.height),
                    "seed": str(req.seed),
                }
                r = await self.client.post(
                    self.url, files={k: (None, v) for k, v in fields.items()}
                )
        except httpx.TransportError as e:
            raise CloudflareImageError(f"Cloudflare에 연결할 수 없다: {e}") from e

        body = _json(r)
        if r.status_code != 200 or not body.get("success", True):
            msg = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in body.get("errors", []))
            msg = msg or r.text[:300]
            if r.status_code == 429 or "4006" in msg or "allocation" in msg.lower():
                raise ImageQuotaExceeded(f"Cloudflare 이미지 무료 한도 초과: {msg}")
            raise CloudflareImageError(f"Cloudflare 이미지 생성 실패 HTTP {r.status_code}: {msg}")

        b64 = (body.get("result") or {}).get("image")
        if not b64:
            raise CloudflareImageError("Cloudflare 응답에 이미지가 없다")
        data = base64.b64decode(b64)
        self.meter.record(self.model, cost)
        ext = ".png" if data.startswith(b"\x89PNG") else ".jpg"
        out = req.out_path.with_suffix(ext)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return ImageResult(path=out, source="generated", provider=self.provider)


def _json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {}
