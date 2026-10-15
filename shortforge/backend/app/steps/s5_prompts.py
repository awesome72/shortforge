"""S5 자산: 장면별 이미지 프롬프트 + TTS 대본, 그리고 실제 자산 생성 (F-5.1~F-5.3).

- 이미지: 본인 소재(user_media)가 있으면 장면 순서대로 우선 배정하고 생성을 건너뛴다.
  나머지는 이미지 어댑터에 맡긴다(IMAGE_MODE=upload면 생성하지 않고 프롬프트만 남긴다).
  생성하지 못한 장면은 본인 사진을 순환해 채운다(경고). 사진도 없으면 S6에서 막힌다.
- 음성: 대사를 TTS용으로 다듬어(tts_script) 합성하고 길이·어절 타이밍을 기록한다.
  숫자는 바꾸지 않는다 — 자막이 TTS 어절에서 나오므로 "10분"을 "십 분"으로 바꾸면 자막도 바뀐다.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Asset, ImageAsset, Input, Strategy, VoiceAsset

NEGATIVE = "text, watermark, logo, blurry, deformed hands, extra fingers, low quality"


def tts_script(line: str) -> str:
    """대사 → TTS 대본: 이모지·해시태그·괄호 지문·물결을 지우고 끝 문장부호로 호흡을 맞춘다."""
    text = re.sub(r"#\S+", " ", line)
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)
    text = "".join(
        ch
        for ch in text
        if unicodedata.category(ch) not in ("So", "Sk", "Cf", "Mn") or ch.isalnum()
    )
    text = text.replace("~", " ").replace("...", "…")
    text = " ".join(text.split())
    if text and text[-1] not in ".!?…":
        text += "."
    return text


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
    reused: list[str] = []
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
            if out is not None:
                image.path = _rel(ctx, out)
            elif inp.user_media:
                image.source = "user"
                image.path = inp.user_media[i % len(inp.user_media)]
                reused.append(scene.id)
            else:
                missing_images.append(scene.id)

        text = tts_script(scene.line)
        if not text.strip(".!?… "):
            raise StepInputError(f"{scene.id} 대사가 비어 있다 (이모지·해시태그만 있음)")
        voice = VoiceAsset(text=text, voice=ctx.settings.tts_voice)
        tts = await ctx.adapters.tts.synthesize(
            voice.text, voice.voice, voice.rate, assets_dir / f"{scene.id}.mp3"
        )
        voice.path = _rel(ctx, tts.path)
        voice.duration_sec = tts.duration_sec
        voice.words_path = _rel(ctx, tts.words_path) if tts.words_path else None

        assets.append(Asset(scene_id=scene.id, image=image, voice=voice))

    if reused:
        ctx.warn(
            f"사진 {len(inp.user_media)}장을 {len(strategy.scenes)}장면에 나눠 쓰느라 "
            f"{', '.join(reused)}에 같은 사진을 다시 썼다 — 사진을 더 올리면 바뀐다"
        )
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
