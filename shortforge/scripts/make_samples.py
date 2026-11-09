"""다듬기 화면의 견본(그림 느낌 4장, 목소리 2개)을 만든다. 결과는 frontend/public/samples/에 커밋한다.

사용법 (shortforge/backend에서):
    uv run python ../scripts/make_samples.py [--skip-images] [--skip-voices]
비용: Cloudflare 그림 4장(장당 약 156 Neurons, 하루 무료 10,000, 영문 프롬프트만 보낸다),
Edge-TTS 목소리 2개(앱과 같은 무료 합성). 그림 방식이나 목소리를 바꾸면 다시 만든다.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.base import ImageRequest  # noqa: E402
from app.adapters.registry import _cloudflare  # noqa: E402
from app.config import Settings  # noqa: E402
from app.image_prompt import VISUAL_STYLES, build_prompt  # noqa: E402
from app.media import find_exe  # noqa: E402
from app.steps.s5_prompts import KO_VOICES  # noqa: E402

OUT = ROOT / "frontend" / "public" / "samples"
SCENE = "a cup of latte with heart latte art on a wooden table by a sunny window, a small plant beside it"
LINE = "안녕하세요. 이 목소리로 대사를 읽어 드려요."


async def images(s: Settings) -> None:
    cf = _cloudflare(s)
    work = s.data_dir / "samples"
    work.mkdir(parents=True, exist_ok=True)
    for i, (name, style) in enumerate(VISUAL_STYLES.items()):
        prompt = build_prompt(SCENE, style)
        res = await cf.generate(ImageRequest(prompt, "", 7300 + i, work / name))
        # 58px 견본의 3배, 3:4로 가운데를 잘라 작게 (장당 수 KB)
        subprocess.run(
            [find_exe("ffmpeg"), "-y", "-v", "error", "-i", str(res.path),
             "-vf", "crop=iw:iw*4/3,scale=174:232", "-c:v", "libwebp", "-quality", "72",
             str(OUT / f"style-{name}.webp")],
            check=True,
        )  # fmt: skip
        print(f"style-{name}.webp ← {res.provider}")


async def voices() -> None:
    import edge_tts

    for key, voice in (("female", KO_VOICES["woman"]), ("male", KO_VOICES["man"])):
        path = OUT / f"voice-{key}.mp3"
        await edge_tts.Communicate(LINE, voice).save(str(path))
        print(f"voice-{key}.mp3 ← {voice} ({path.stat().st_size // 1024}KB)")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-images", action="store_true")
    ap.add_argument("--skip-voices", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.skip_images:
        await images(Settings())
    if not args.skip_voices:
        await voices()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
