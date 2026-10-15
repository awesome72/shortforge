"""S5 자산: 장면별 이미지 프롬프트 + TTS 대본, 그리고 실제 자산 생성 (F-5.1~F-5.3).

- 이미지: 본인 소재(user_media)가 있으면 장면 순서대로 우선 배정하고 생성을 건너뛴다.
  나머지는 이미지 어댑터에 맡긴다(IMAGE_MODE=upload면 생성하지 않고 프롬프트만 남긴다).
- 음성: 대사를 TTS로 합성하고 길이를 기록한다. 숫자 한글화 등 대본 다듬기는 Step 5에서 보강한다.
"""

from __future__ import annotations

import hashlib

from app.orchestrator import StepContext
from app.schemas.project import Asset, ImageAsset, Input, Strategy, VoiceAsset

NEGATIVE = "text, watermark, logo, blurry, deformed hands, extra fingers, low quality"


def style_seed_number(style_seed: str) -> int:
    """같은 style_seed면 같은 이미지 seed (장면 간 일관성)."""
    return int(hashlib.sha256(style_seed.encode()).hexdigest()[:8], 16) % (2**31)


async def run(ctx: StepContext) -> list[Asset]:
    inp: Input = ctx.read("input")
    strategy: Strategy = ctx.read("strategy")
    seed = style_seed_number(strategy.style_seed)
    assets_dir = ctx.project_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    assets: list[Asset] = []
    missing_images: list[str] = []
    for i, scene in enumerate(strategy.scenes):
        await ctx.progress(f"asset:{scene.id}", i / len(strategy.scenes))

        image = ImageAsset(
            prompt=f"{scene.visual}, {strategy.style_seed}", negative=NEGATIVE, seed=seed
        )
        if i < len(inp.user_media):
            image.source = "user"
            image.path = inp.user_media[i]
        else:
            out = await ctx.adapters.image.generate(
                image.prompt, image.negative, image.seed, assets_dir / f"{scene.id}.png"
            )
            if out is None:
                missing_images.append(scene.id)
            else:
                image.path = _rel(ctx, out)

        voice = VoiceAsset(text=scene.line.strip(), voice=ctx.settings.tts_voice)
        tts = await ctx.adapters.tts.synthesize(
            voice.text, voice.voice, voice.rate, assets_dir / f"{scene.id}.mp3"
        )
        voice.path = _rel(ctx, tts.path)
        voice.duration_sec = tts.duration_sec
        voice.words_path = _rel(ctx, tts.words_path) if tts.words_path else None

        assets.append(Asset(scene_id=scene.id, image=image, voice=voice))

    if missing_images:
        ctx.warn(
            f"이미지가 없는 장면: {', '.join(missing_images)} — 사진을 올리거나 프롬프트로 만든 "
            "이미지를 업로드한다"
        )
    return assets


def _rel(ctx: StepContext, path) -> str:
    try:
        return path.relative_to(ctx.project_dir).as_posix()
    except ValueError:
        return str(path)
