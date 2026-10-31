"""실제 Hugging Face로 장면 그림 한 장을 영상으로 만들어 본다 (D19 시험, 비용 발생).

    uv run python ../scripts/videogen_smoke.py 그림.png --prompt "a woman stretching" --yes

한 번에 약 $0.05~0.14가 HF_TOKEN 계정의 크레딧에서 나간다. --yes가 없으면 값만 보여 주고 멈춘다.
걸린 시간, 파일 크기, 영상 크기·길이를 출력한다. 하루 예산(VIDEO_GEN_DAILY_BUDGET_USD)을 지킨다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.adapters.base import VideoGenRequest  # noqa: E402
from app.adapters.video_gen.hf import HFVideoGen, estimate_usd  # noqa: E402
from app.config import Settings  # noqa: E402
from app.media import find_exe  # noqa: E402
from app.spend import VIDEO_PROVIDER, SpendMeter  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--prompt", default="a person in a calm room, soft window light")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, help="기본은 data/videogen_smoke.mp4 (git 제외)")
    ap.add_argument("--yes", action="store_true", help="실제로 호출한다 (비용 발생)")
    args = ap.parse_args()

    settings = Settings()
    out = (args.out or settings.data_dir / "videogen_smoke.mp4").resolve()
    if not settings.hf_token:
        print("HF_TOKEN이 없습니다. 웹 UI 설정 → 영상 만들기에서 넣어 주세요.")
        return 1
    cost = estimate_usd(args.seconds)
    print(f"이번 호출 예상 비용: ${cost:.3f} ({args.seconds}초)")
    if not args.yes:
        print("실제로 만들려면 --yes를 붙여 주세요.")
        return 0

    budget = settings.video_gen_daily_budget_usd
    adapter = HFVideoGen(settings.hf_token, SpendMeter(settings.db_path, budget, VIDEO_PROVIDER))
    started = time.monotonic()
    result = await adapter.generate(
        VideoGenRequest(args.image, args.prompt, args.seed, args.seconds, out)
    )
    print(f"걸린 시간: {time.monotonic() - started:.1f}초")
    print(f"파일: {result.path} ({result.path.stat().st_size / 1_000_000:.2f}MB)")
    probe = subprocess.run(
        [find_exe("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(result.path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    print(json.dumps(json.loads(probe.stdout), ensure_ascii=False))
    print(f"오늘 사용액(어림): ${adapter.spend.used():.3f} / ${budget:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
