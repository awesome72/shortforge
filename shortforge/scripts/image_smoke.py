"""무료 이미지 소스 실측 (D12): Cloudflare 1장 생성 + Pixabay 1장 검색.

사용법 (shortforge/backend에서):
    uv run python ../scripts/image_smoke.py [--prompt "..."] [--query "..."] [--skip-cloudflare]
비용: Cloudflare 약 156 Neurons(하루 무료 10,000), Pixabay 검색 1회(24시간 캐시).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.base import ImageRequest  # noqa: E402
from app.adapters.registry import _cloudflare, _pixabay  # noqa: E402
from app.config import Settings  # noqa: E402
from app.media import find_exe  # noqa: E402


def size(path: Path) -> str:
    out = subprocess.run(
        [find_exe("ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,codec_name", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    st = json.loads(out.stdout)["streams"][0]
    return f"{st['width']}×{st['height']} {st['codec_name']}"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="hands tying running shoes on a yoga mat in a cozy living room "
                    "at night, warm lamp light, vertical 9:16, realistic photo, no text")  # fmt: skip
    ap.add_argument("--query", default="home workout yoga mat")
    ap.add_argument("--skip-cloudflare", action="store_true")
    args = ap.parse_args()

    s = Settings()
    out = s.data_dir / "image_smoke"
    out.mkdir(parents=True, exist_ok=True)

    if not args.skip_cloudflare:
        cf = _cloudflare(s)
        before = cf.meter.used()
        t = time.perf_counter()
        res = await cf.generate(ImageRequest(args.prompt, "", 4127, out / "cloudflare"))
        print(f"[Cloudflare {res.provider}] {time.perf_counter() - t:.1f}초 · {size(res.path)} · "
              f"{res.path.stat().st_size // 1024}KB · Neurons +{cf.meter.used() - before:.0f} "
              f"(오늘 {cf.meter.used():.0f}/{cf.meter.daily_limit:,}) → {res.path}")  # fmt: skip

    px = _pixabay(s)
    t = time.perf_counter()
    res = await px.generate(ImageRequest(args.prompt, "", 0, out / "pixabay", query=args.query))
    if res is None:
        print(f"[Pixabay] '{args.query}' 검색 결과 없음")
    else:
        print(f"[Pixabay] {time.perf_counter() - t:.1f}초 · {size(res.path)} · {res.credit} → {res.path}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
