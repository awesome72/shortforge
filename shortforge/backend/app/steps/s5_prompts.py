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
from app.image_check import check_images
from app.image_prompt import (
    PROMPT_REV,
    align_gender,
    apply_subject,
    apply_visual_style,
    build_prompt,
    clean_image_prompt,
    fix_subject,
    gender_in,
    has_person,
    narrator_gender,
    visual_style,
)
from app.llm import load_prompt
from app.modes import scene_media
from app.orchestrator import StepContext, StepInputError
from app.readiness import image_hint
from app.schemas.project import (
    LAST_SCENE_EXTRA_PAD,
    Asset,
    ImageAsset,
    Input,
    Strategy,
    TimelineScene,
    VoiceAsset,
)

NEGATIVE = "text, watermark, logo, blurry, deformed hands, extra fingers, low quality"
PAD = TimelineScene.model_fields["pad"].default  # S6가 장면마다 붙이는 여백과 같은 값
DURATION_TOLERANCE = 0.15
# 길 때는 5%만 넘어도 조금 빠르게 맞춘다(빨라지는 쪽은 자연스럽다). 짧을 때는 15%까지 두고
# S6의 장면 여백이 메운다(많이 늦추면 늘어져 들린다).
# 2026-10: 30초 목표에 33.4초(+11%)가 그대로 나갔다
OVER_TOLERANCE = 0.05
RATE_MIN, RATE_MAX = (
    -0.10,
    0.25,
)  # 이 밖은 부자연스럽게 들린다 (느리게는 -10%까지만: -18%는 늘어져 들렸다)
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
    style: str = ""  # 모든 장면 공통 시각 스타일 (영문, 자막·레이아웃 제외)
    subject: str = ""  # 주인공 한 명의 고정 묘사 (장면마다 다른 사람이 나오지 않게)
    scenes: list[ScenePrompt]


async def fetch_image(adapter: ImageAdapter, image: ImageAsset, out_path: Path, base: Path) -> bool:
    """어댑터로 이미지를 만들거나 찾아 image에 채운다. 얻지 못하면 False.

    S5 전체 실행과 API의 "장면 이미지 다시 만들기"가 함께 쓴다.
    """
    # 예전 규칙으로 만든 프롬프트(자막·화면비 문구 포함)도 요청 직전에 한 번 더 거른다
    image.prompt = clean_image_prompt(image.prompt) or image.prompt
    result = await adapter.generate(
        ImageRequest(
            image.prompt,
            image.negative,
            image.seed,
            out_path,
            query=image.query,
            person=has_person(image.prompt),
        )
    )
    if result is None:
        return False
    image.rev = PROMPT_REV
    image.still = None  # 새 그림이다 (움직여 만든 영상의 원본 기록을 남기지 않는다)
    image.check = None
    try:
        image.path = result.path.relative_to(base).as_posix()
    except ValueError:
        image.path = str(result.path)
    image.source, image.provider, image.credit = result.source, result.provider, result.credit
    return True


async def unify_sources(
    adapter: ImageAdapter, made: list[Asset], assets_dir: Path, ctx: StepContext
) -> None:
    """한 영상 안에서 그림을 만든 곳이 바뀌면(앞 장면은 Cloudflare, 한도 뒤로는 Hugging Face)
    그림체가 섞인다. 한도가 바닥난 곳에서 만든 그림을 다음 소스로 다시 그려 맞춘다(D22)."""
    exhausted = set(getattr(adapter, "_exhausted", ()))
    generated = [a for a in made if a.image.source == "generated"]
    makers = {(a.image.provider or "").split(":")[0] for a in generated}
    if len(makers) < 2 or not exhausted:
        return
    redo = [a for a in generated if (a.image.provider or "").split(":")[0] in exhausted]
    fixed = []
    for a in redo:
        image = a.image.model_copy()
        if not await fetch_image(
            adapter, image, assets_dir / image_stem(a.scene_id, image), ctx.project_dir
        ):
            continue
        maker = (image.provider or "").split(":")[0]
        if image.source != "generated" or maker in exhausted:
            # 다음 생성 소스도 막혀 무료 사진 등으로 떨어졌다: 멀쩡한 원래 그림을 둔다
            if image.path and image.path != a.image.path:
                (ctx.project_dir / image.path).unlink(missing_ok=True)
            continue
        a.image = image
        fixed.append(a.scene_id)
    if fixed:
        ctx.warn(f"그림을 만드는 곳이 중간에 바뀌어 {', '.join(fixed)}을 다시 그려 그림체를 맞췄다")


async def english_prompts(
    ctx: StepContext, strategy: Strategy, gender: str
) -> tuple[dict[str, ScenePrompt], str]:
    """장면 묘사 → 영문 이미지 프롬프트·검색어와 공통 스타일 (경량 LLM 1회).

    실패하면 ({}, "")로 한국어 묘사로 진행한다.
    """
    inp: Input = ctx.read("input")
    lines = [
        f"style_seed: {strategy.style_seed}",
        f"audience: {inp.audience}",
        f"region: {inp.region}",
        "",
    ]
    lines += [f"{s.id} role={s.role} visual={s.visual!r} line={s.line!r}" for s in strategy.scenes]
    try:
        prompt = load_prompt("s5_image_prompts").text
        out = await ctx.adapters.llm.generate_json(
            "s5_image_prompts", prompt, "\n".join(lines), ImagePromptsOut
        )
    except Exception as e:
        ctx.warn(f"영문 이미지 프롬프트 변환에 실패해 한국어 묘사로 진행했다 ({type(e).__name__})")
        return {}, ""
    # 모델이 지시와 달리 성별을 빼면("a Korean person …") 장면마다 다른 사람이 나온다
    seed = style_seed_number(strategy.style_seed)
    subject = fix_subject(out.subject, inp.audience, seed, gender)
    # 주인공 묘사만 바꾸면 장면에 남은 "her neck", "tired woman sofa" 때문에 성별이 섞인다
    target = gender_in([subject])
    scenes = {
        p.id: p.model_copy(
            update={
                "prompt": align_gender(
                    apply_subject(p.prompt, out.subject, subject), target, original=p.prompt
                ),
                "query": align_gender(p.query, target),
            }
        )
        for p in out.scenes
    }
    return scenes, apply_visual_style(visual_style(out.style), inp.visual_style)


def image_basis(visual: str, style_seed: str, look: str = "auto") -> str:
    """같은 basis면 이전 이미지를 다시 쓴다. 그림체를 고르면 basis가 바뀌어 새로 만든다."""
    base = f"{visual.strip()}|{style_seed.strip()}"
    return base if look == "auto" else f"{base}|{look}"


def image_stem(scene_id: str, image: ImageAsset) -> str:
    """생성 이미지 파일 이름. 내용 해시를 붙여, 장면 번호가 바뀌어도
    재사용 중인 다른 장면의 파일을 덮어쓰지 않게 한다."""
    h = hashlib.sha256(f"{image.prompt}|{image.query}".encode()).hexdigest()[:6]
    return f"{scene_id}_{image.seed}_{h}"


def reusable_images(ctx: StepContext, user_media: list[str]) -> dict[str, ImageAsset]:
    """이전 S5 출력에서 다시 쓸 수 있는 이미지 {basis: ImageAsset}. 파일이 남아 있는 것만."""
    out: dict[str, ImageAsset] = {}
    clips: list[ImageAsset] = []
    for a in ctx.current() or []:
        img = a.image
        if not img.basis or not img.path:
            continue
        # 1단계 사진 목록은 장면 순서대로 다시 배정하므로 재사용 대상이 아니다.
        # 장면별로 고른 사진(사진 교체·후보·생성)만 파일이 남아 있으면 다시 쓴다.
        if img.source == "user" and img.path in user_media:
            continue
        if not (ctx.project_dir / img.path).is_file():
            continue
        # 장면에 직접 올린 사진은 그 장면의 것이다: 사진으로 다 채우는 소상공인 모드도 남긴다
        if img.source == "user":
            out[_scene_key(a.scene_id, "own")] = img
        # 예전 프롬프트 규칙으로 생성한 이미지(자막 글씨가 그려지던 것)는 다시 만든다.
        # 돈을 들여 움직인 영상(D19)은 사용자가 고른 결과라 규칙이 바뀌어도 남긴다
        if img.source == "generated" and img.rev < PROMPT_REV and img.still is None:
            continue
        # 영상은 그 장면의 것이다: 묘사가 같은 다른 장면으로 번지지 않게 장면 키로 남긴다
        if img.still is not None:
            out[_scene_key(a.scene_id, img.basis)] = img
            if img.still.source == "user":  # 사진을 움직인 영상은 그림 느낌과 상관없다
                out[_scene_key(a.scene_id, _photo_key(img.basis))] = img
            if img.still.path in user_media:  # 1단계 사진이 다시 배정되면 영상을 그대로 쓴다
                out[_clip_key(img.still.path)] = img
            clips.append(img)
            continue
        if img.basis in out:
            continue
        out[img.basis] = img
        # 장면에 직접 올린 사진은 그림 느낌과 상관없다: 그림 느낌을 바꿔도(basis가 바뀌어도) 남긴다
        if img.source == "user":
            out.setdefault(_photo_key(img.basis), img)
    # 장면이 바뀌어 장면 키가 맞지 않을 때의 대비. 일반 그림 자리를 빼앗지 않게 맨 뒤에 넣는다
    for img in clips:
        out.setdefault(img.basis, img)
        if img.still.source == "user":
            out.setdefault(_photo_key(img.basis), img)
    return out


def _clip_key(photo: str) -> str:
    return "clip:" + photo


def _scene_key(scene_id: str, basis: str) -> str:
    return f"scene:{scene_id}:{basis}"


def _photo_key(basis: str) -> str:
    """장면 사진의 재사용 키 (basis에서 그림 느낌을 뺀 장면 묘사|스타일 시드)."""
    return "photo:" + "|".join(basis.split("|")[:2])


def _reuse(previous: dict[str, ImageAsset], basis: str, scene_id: str) -> ImageAsset | None:
    return (
        previous.get(_scene_key(scene_id, basis))
        or previous.get(_scene_key(scene_id, _photo_key(basis)))
        or previous.get(basis)
        or previous.get(_photo_key(basis))
    )


# 한국어 Edge-TTS 목소리. 남성은 InJoon(5.5자/초)이 SunHi(6.2자/초)보다 느려 같은 대사가 길어지고
# 속도를 +25%까지 올려야 했다. Hyunsu(6.4자/초)는 SunHi와 빠르기가 비슷하다 (2026-10-24 실측)
KO_VOICES = {"woman": "ko-KR-SunHiNeural", "man": "ko-KR-HyunsuMultilingualNeural"}
# 설정의 TTS_VOICE가 이 중 하나면 '자동'으로 본다 (직접 다른 목소리를 골랐으면 그대로 쓴다)
KO_DEFAULT_VOICES = {*KO_VOICES.values(), "ko-KR-InJoonNeural"}


def narrator_voice(ctx: StepContext, inp: Input, gender: str) -> str:
    """1단계 목소리 선택(자동·여성·남성)에 맞는 Edge-TTS 목소리.

    한국어가 아니거나, 설정에서 다른 한국어 목소리를 직접 골라 두었고 '자동'이면 설정을 따른다.
    """
    configured = ctx.settings.tts_voice
    if inp.lang != "ko" or ctx.settings.tts_mode != "edge":
        return configured
    if inp.voice == "auto" and configured not in KO_DEFAULT_VOICES:
        return configured
    return KO_VOICES[gender]


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
    media = scene_media(inp, len(strategy.scenes), [s.role for s in strategy.scenes])
    if inp.mode == "business" and not media:
        raise StepInputError(
            "가게 홍보 영상은 실제 사진이 필요해요. 사진을 한 장 이상 올려 주세요.",
            "need_photos",
        )
    previous = reusable_images(ctx, media)
    # 내레이션(=주인공) 성별: 이미 만든 그림이 있으면 그 주인공을 따른다 (목소리·새 그림 모두)
    existing = gender_in([img.prompt for img in previous.values() if img.source == "generated"])
    gender = narrator_gender(inp.audience, seed, inp.voice, existing)
    needs_images = any(
        _reuse(previous, image_basis(s.visual, strategy.style_seed, inp.visual_style), s.id) is None
        for s in strategy.scenes[len(media) :]
    )
    assets: list[Asset] = []
    kept: list[str] = []
    # 영문 프롬프트를 채울 장면 (재사용 이미지는 이전 프롬프트를 그대로 둔다).
    # 본인 사진 장면도 채운다 — 그 장면에서 "다른 이미지"를 누르면 이 프롬프트로 만든다
    translate: list[Asset] = []
    for i, scene in enumerate(strategy.scenes):
        text = tts_script(scene.line)
        if not text.strip(".!?… "):
            raise StepInputError(f"{scene.id} 대사가 비어 있다 (이모지·해시태그만 있음)")
        basis = image_basis(scene.visual, strategy.style_seed, inp.visual_style)
        image = ImageAsset(
            prompt=build_prompt(
                scene.visual,
                apply_visual_style(visual_style(strategy.style_seed), inp.visual_style),
                quality=False,
            ),
            negative=NEGATIVE,
            seed=seed,
            query=scene.visual,
            basis=basis,
            rev=PROMPT_REV,
        )
        voice = VoiceAsset(text=text, voice=narrator_voice(ctx, inp, gender))
        asset = Asset(scene_id=scene.id, image=image, voice=voice)
        again = _reuse(previous, basis, scene.id)
        clip = previous.get(_clip_key(media[i])) if i < len(media) else None
        if clip is None and inp.mode == "business":
            clip = previous.get(_scene_key(scene.id, "own"))
        if clip is not None:
            asset.image = clip.model_copy(update={"basis": basis})
            kept.append(scene.id)
        elif again is not None and i >= len(media):
            asset.image = again.model_copy(update={"basis": basis})
            kept.append(scene.id)
        else:
            if i < len(media):
                image.source, image.path = "user", media[i]
            translate.append(asset)
        assets.append(asset)

    missing_images: list[str] = []
    reused: list[str] = []

    async def images() -> None:
        # 영문 프롬프트(LLM) → 이미지 생성·검색. 생성 1장에 십여 초가 걸려 동시에 만든다
        if needs_images and adapter.wants_english_prompts:
            prompts, style = await english_prompts(ctx, strategy, gender)
            for a in translate:
                en = prompts.get(a.scene_id)
                if en:
                    a.image.prompt = build_prompt(en.prompt, style)
                    a.image.query = en.query
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
        made = [a for a, ok in zip(pending, results, strict=True) if ok]
        await unify_sources(adapter, made, assets_dir, ctx)
        for a, ok in zip(pending, results, strict=True):
            if ok:
                continue
            if inp.user_media:  # 이미지를 얻지 못하면 본인 사진을 돌려 쓴다
                i = assets.index(a)
                a.image.source, a.image.path = "user", inp.user_media[i % len(inp.user_media)]
                reused.append(a.scene_id)
            else:
                missing_images.append(a.scene_id)

    async def voices() -> None:
        await _synthesize_all(ctx, assets, assets_dir, rate=0.0)
        await _fit_duration(ctx, assets, assets_dir, target=strategy.scenes[-1].end)

    # 음성은 이미지와 상관이 없으므로 기다리지 않고 함께 만든다. 한쪽이 실패하면 다른 쪽도 멈춘다
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(images())
            tg.create_task(voices())
    except* Exception as eg:
        raise eg.exceptions[0] from None

    for note in await check_images(ctx.adapters.llm, assets, ctx.project_dir):
        ctx.warn(note)
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
        ctx.warn(f"이미지가 없는 장면: {', '.join(missing_images)} — {image_hint(ctx.settings)}")
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
        a.voice.speech_sec = tts.speech_sec
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
    pads = PAD * len(assets) + LAST_SCENE_EXTRA_PAD
    total = sum(a.voice.length or 0 for a in assets) + pads
    if target * (1 - DURATION_TOLERANCE) <= total <= target * (1 + OVER_TOLERANCE):
        return
    needed = fit_rate(total - pads, target - pads, current=0.0)
    if abs(needed) >= MIN_RATE_STEP:
        await _synthesize_all(ctx, assets, assets_dir, rate=needed)
        total = sum(a.voice.length or 0 for a in assets) + pads
        ctx.warn(
            f"음성 길이를 목표 {target:g}초에 맞추려고 말하기 속도를 {format_rate(needed)}로 "
            f"조정했다 → {total:.1f}초"
        )
    if abs(total - target) > target * DURATION_TOLERANCE:
        hint = "대사를 보강한다" if total < target else "대사를 줄인다"
        ctx.warn(
            f"속도 조정 한도({format_rate(RATE_MIN)}~{format_rate(RATE_MAX)})로도 {total:.1f}초 — "
            f"목표 {target:g}초와 차이가 크다. "
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
