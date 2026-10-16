"""S5 자산: 장면별 이미지 프롬프트 + TTS 대본, 그리고 실제 자산 생성 (F-5.1~F-5.3).

- 이미지: 본인 소재(user_media)가 있으면 장면 순서대로 우선 배정하고 생성을 건너뛴다.
  나머지는 이미지 어댑터(체인: Cloudflare 생성 → Pexels 사진 등, D12)에 맡긴다.
  생성·검색 어댑터면 경량 LLM 1회로 장면 묘사를 영문 프롬프트·사진 검색어로 바꾼다.
  IMAGE_MODE=upload면 생성하지 않고 프롬프트만 남긴다.
  이미지를 얻지 못한 장면은 본인 사진을 순환해 채운다(경고). 사진도 없으면 S6에서 막힌다.
- 다시 실행할 때: 장면 묘사(visual)와 스타일 시드가 그대로인 장면은 이전 이미지를 그대로 쓴다
  (`ImageAsset.basis`로 비교, 장면 순서·번호가 바뀌어도 따라간다). 사용자가 고른 후보·교체한 사진과
  무료 생성 한도를 지키기 위해서다. 바꾸고 싶으면 장면별 "다른 이미지"를 쓴다.
- 음성: 대사를 TTS용으로 다듬어(tts_script) 합성하고 길이·어절 타이밍을 기록한다.
  숫자는 바꾸지 않는다 — 자막이 TTS 어절에서 나오므로 "10분"을 "십 분"으로 바꾸면 자막도 바뀐다.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel

from app.adapters.base import ImageAdapter, ImageRequest
from app.llm import load_prompt
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Asset, ImageAsset, Input, Strategy, TimelineScene, VoiceAsset

NEGATIVE = "text, watermark, logo, blurry, deformed hands, extra fingers, low quality"
PAD = TimelineScene.model_fields["pad"].default  # S6가 장면마다 붙이는 여백과 같은 값
DURATION_TOLERANCE = 0.15
RATE_MIN, RATE_MAX = -0.20, 0.25  # 이 밖은 부자연스럽게 들린다
MIN_RATE_STEP = 0.03  # 이보다 작은 조정은 다시 합성할 가치가 없다
TTS_CONCURRENCY = 3
IMAGE_CONCURRENCY = 3  # Cloudflare 생성은 1장에 약 15초 (2026-10 실측)


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


class ScenePrompt(BaseModel):
    id: str
    prompt: str  # 영문 이미지 생성 프롬프트
    query: str  # 사진 검색용 영문 키워드 2~4단어


class ImagePromptsOut(BaseModel):
    scenes: list[ScenePrompt]


async def fetch_image(adapter: ImageAdapter, image: ImageAsset, out_path: Path, base: Path) -> bool:
    """어댑터로 이미지를 만들거나 찾아 image에 채운다. 얻지 못하면 False.

    S5 전체 실행과 API의 "장면 이미지 다시 만들기"가 함께 쓴다.
    """
    result = await adapter.generate(
        ImageRequest(image.prompt, image.negative, image.seed, out_path, query=image.query)
    )
    if result is None:
        return False
    try:
        image.path = result.path.relative_to(base).as_posix()
    except ValueError:
        image.path = str(result.path)
    image.source, image.provider, image.credit = result.source, result.provider, result.credit
    return True


async def english_prompts(ctx: StepContext, strategy: Strategy) -> dict[str, ScenePrompt]:
    """장면 묘사 → 영문 이미지 프롬프트·검색어 (경량 LLM 1회). 실패하면 빈 dict(한국어로 진행)."""
    lines = [f"{s.id} role={s.role} visual={s.visual!r} line={s.line!r}" for s in strategy.scenes]
    try:
        prompt = load_prompt("s5_image_prompts").text
        out = await ctx.adapters.llm.generate_json(
            "s5_image_prompts", prompt, "\n".join(lines), ImagePromptsOut
        )
    except Exception as e:
        ctx.warn(f"영문 이미지 프롬프트 변환에 실패해 한국어 묘사로 진행했다 ({type(e).__name__})")
        return {}
    return {p.id: p for p in out.scenes}


def image_basis(visual: str, style_seed: str) -> str:
    return f"{visual.strip()}|{style_seed.strip()}"


def image_stem(scene_id: str, image: ImageAsset) -> str:
    """생성 이미지 파일 이름. 내용 해시를 붙여, 장면 번호가 바뀌어도
    재사용 중인 다른 장면의 파일을 덮어쓰지 않게 한다."""
    h = hashlib.sha256(f"{image.prompt}|{image.query}".encode()).hexdigest()[:6]
    return f"{scene_id}_{image.seed}_{h}"


def reusable_images(ctx: StepContext, user_media: list[str]) -> dict[str, ImageAsset]:
    """이전 S5 출력에서 다시 쓸 수 있는 이미지 {basis: ImageAsset}. 파일이 남아 있는 것만."""
    out: dict[str, ImageAsset] = {}
    for a in ctx.current() or []:
        img = a.image
        if not img.basis or not img.path or img.basis in out:
            continue
        # 1단계 사진 목록은 장면 순서대로 다시 배정하므로 재사용 대상이 아니다.
        # 장면별로 고른 사진(사진 교체·후보·생성)만 파일이 남아 있으면 다시 쓴다.
        if img.source == "user" and img.path in user_media:
            continue
        if not (ctx.project_dir / img.path).is_file():
            continue
        out[img.basis] = img
    return out


def style_seed_number(style_seed: str) -> int:
    """같은 style_seed면 같은 이미지 seed (장면 간 일관성)."""
    return int(hashlib.sha256(style_seed.encode()).hexdigest()[:8], 16) % (2**31)


async def run(ctx: StepContext) -> list[Asset]:
    inp: Input = ctx.read("input")
    strategy: Strategy = ctx.read("strategy")
    seed = style_seed_number(strategy.style_seed)
    assets_dir = ctx.project_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    adapter = ctx.adapters.image
    previous = reusable_images(ctx, inp.user_media)
    needs_images = any(
        image_basis(s.visual, strategy.style_seed) not in previous
        for s in strategy.scenes[len(inp.user_media) :]
    )
    prompts = (
        await english_prompts(ctx, strategy)
        if needs_images and adapter.wants_english_prompts
        else {}
    )

    assets: list[Asset] = []
    kept: list[str] = []
    for i, scene in enumerate(strategy.scenes):
        text = tts_script(scene.line)
        if not text.strip(".!?… "):
            raise StepInputError(f"{scene.id} 대사가 비어 있다 (이모지·해시태그만 있음)")
        en = prompts.get(scene.id)
        basis = image_basis(scene.visual, strategy.style_seed)
        image = ImageAsset(
            prompt=f"{en.prompt if en else scene.visual}, {strategy.style_seed}",
            negative=NEGATIVE,
            seed=seed,
            query=en.query if en else scene.visual,
            basis=basis,
        )
        if i < len(inp.user_media):
            image.source, image.path = "user", inp.user_media[i]
        elif basis in previous:
            image = previous[basis].model_copy()
            kept.append(scene.id)
        voice = VoiceAsset(text=text, voice=ctx.settings.tts_voice)
        assets.append(Asset(scene_id=scene.id, image=image, voice=voice))

    # 본인 사진이 없는 장면만 이미지 소스에 맡긴다. 생성 1장에 십여 초가 걸려 동시에 만든다
    pending = [a for a in assets if a.image.path is None]
    sem = asyncio.Semaphore(IMAGE_CONCURRENCY)
    done = 0

    async def one(a: Asset) -> bool:
        nonlocal done
        async with sem:
            ok = await fetch_image(
                adapter, a.image, assets_dir / image_stem(a.scene_id, a.image), ctx.project_dir
            )
        done += 1
        await ctx.progress("images", done / len(pending))
        return ok

    results = await asyncio.gather(*(one(a) for a in pending))
    missing_images: list[str] = []
    reused: list[str] = []
    for a, ok in zip(pending, results, strict=True):
        if ok:
            continue
        if inp.user_media:  # 이미지를 얻지 못하면 본인 사진을 돌려 쓴다
            i = assets.index(a)
            a.image.source, a.image.path = "user", inp.user_media[i % len(inp.user_media)]
            reused.append(a.scene_id)
        else:
            missing_images.append(a.scene_id)

    await _synthesize_all(ctx, assets, assets_dir, rate=0.0)
    await _fit_duration(ctx, assets, assets_dir, target=strategy.scenes[-1].end)

    if kept:
        ctx.warn(
            f"장면 묘사가 그대로인 {', '.join(kept)}은 이전 이미지를 그대로 썼다 — "
            '바꾸려면 5단계 장면 카드의 "다른 이미지"를 누른다'
        )
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


async def _synthesize_all(
    ctx: StepContext, assets: list[Asset], assets_dir: Path, rate: float
) -> None:
    """장면 음성을 동시에 TTS_CONCURRENCY개씩 합성한다."""
    sem = asyncio.Semaphore(TTS_CONCURRENCY)
    done = 0

    async def one(a: Asset) -> None:
        nonlocal done
        a.voice.rate = format_rate(rate)
        async with sem:
            tts = await ctx.adapters.tts.synthesize(
                a.voice.text, a.voice.voice, a.voice.rate, assets_dir / f"{a.scene_id}.mp3"
            )
        a.voice.path = _rel(ctx, tts.path)
        a.voice.duration_sec = tts.duration_sec
        a.voice.words_path = _rel(ctx, tts.words_path) if tts.words_path else None
        done += 1
        await ctx.progress("tts", done / len(assets))

    await asyncio.gather(*(one(a) for a in assets))


async def _fit_duration(
    ctx: StepContext, assets: list[Asset], assets_dir: Path, target: float
) -> None:
    """음성 합계가 목표 ±15%를 벗어나면 말하기 속도를 조정해 한 번 다시 합성한다 (Step 7-6).

    S4는 장면 시간을 '계획'할 뿐이고 실제 길이는 TTS가 정한다. 그 차이를 여기서 메운다.
    """
    pads = PAD * len(assets)
    total = sum(a.voice.duration_sec or 0 for a in assets) + pads
    if abs(total - target) <= target * DURATION_TOLERANCE:
        return
    needed = fit_rate(total - pads, target - pads, current=0.0)
    if abs(needed) >= MIN_RATE_STEP:
        await _synthesize_all(ctx, assets, assets_dir, rate=needed)
        total = sum(a.voice.duration_sec or 0 for a in assets) + pads
        ctx.warn(
            f"음성 길이를 목표 {target:g}초에 맞추려고 말하기 속도를 {format_rate(needed)}로 "
            f"조정했다 → {total:.1f}초"
        )
    if abs(total - target) > target * DURATION_TOLERANCE:
        hint = "대사를 보강한다" if total < target else "대사를 줄인다"
        ctx.warn(
            f"속도 조정 한도(−20%~+25%)로도 {total:.1f}초 — 목표 {target:g}초와 차이가 크다. "
            f"4단계에서 {hint}"
        )


def fit_rate(voice_total: float, voice_target: float, current: float = 0.0) -> float:
    """말하기 시간 ∝ 1/(1+rate). 목표 길이가 되는 rate를 허용 범위로 자른다."""
    if voice_total <= 0 or voice_target <= 0:
        return current
    rate = voice_total / voice_target * (1 + current) - 1
    return max(RATE_MIN, min(RATE_MAX, round(rate, 2)))


def format_rate(rate: float) -> str:
    return f"{round(rate * 100):+d}%"


def _rel(ctx: StepContext, path) -> str:
    try:
        return path.relative_to(ctx.project_dir).as_posix()
    except ValueError:
        return str(path)
