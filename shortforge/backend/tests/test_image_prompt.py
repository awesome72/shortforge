"""이미지 프롬프트 다듬기: 글자·화면비·부정문 조각 제거.

실측: style_seed의 '자막'이 그림에 영문 글씨로 나왔다.
"""

from app.image_prompt import PROMPT_REV, QUALITY, build_prompt, clean_image_prompt, visual_style

REAL_STYLE = (
    "어두운 남색 배경, 또렷한 인물 한 명 클로즈업, 굵은 흰색 자막, 따뜻한 포인트 조명, "
    "세로 9:16 숏폼 스타일"
)


def test_style_seed_loses_caption_and_layout_words():
    want = "어두운 남색 배경, 또렷한 인물 한 명 클로즈업, 따뜻한 포인트 조명"
    assert visual_style(REAL_STYLE) == want


def test_scene_prompt_loses_ratio_negation_and_quoted_text():
    p = (
        'A hand on a desk in a dim room, a note reading "Study Hard", realistic photography, '
        "vertical 9:16 aspect ratio, no face shown, without text"
    )
    want = "A hand on a desk in a dim room, a note reading, realistic photography"
    assert clean_image_prompt(p) == want


def test_keeps_words_that_only_contain_banned_terms():
    assert clean_image_prompt("modern interior design, wooden table") == (
        "modern interior design, wooden table"
    )


def test_build_prompt_adds_quality_once():
    out = build_prompt("hands holding a red pen over a blank page", "navy tones")
    assert out.endswith(QUALITY) and out.count("35mm lens") == 1


async def test_old_generated_images_are_remade_on_rerun(orch, store, adapters, sample_input):
    """예전 규칙(rev<2)으로 생성한 이미지는 S5를 다시 실행할 때 재사용하지 않는다. 사진은 그대로."""
    p = await orch.run_all(store.create(sample_input).id, from_step="s1")
    assets = p.assets
    assert all(a.image.rev == PROMPT_REV for a in assets)
    old = [a.model_copy(deep=True) for a in assets]
    old[0].image.rev = 1  # 예전 생성 이미지
    old[1].image.source, old[1].image.rev = "user", 0  # 사용자가 바꾼 사진
    p = await orch.edit(p.id, "assets", [a.model_dump() for a in old])
    before = len(adapters.image.requests)
    p = await orch.run_step(p.id, "s5")
    remade = adapters.image.requests[before:]
    assert len(remade) == 1  # rev가 낮은 생성 이미지만 다시 만든다
    assert p.assets[1].image.source == "user"


# ── 그림체·주인공 (PROMPT_REV 4) ─────────────────────────


def test_quality_follows_style():
    from app.image_prompt import QUALITY_ILLUSTRATION, QUALITY_PHOTO, build_prompt, quality_for

    assert quality_for("clean illustration style, warm pastel") == QUALITY_ILLUSTRATION
    assert quality_for("soft watercolor palette") == QUALITY_ILLUSTRATION
    assert quality_for("muted warm palette, soft window light") == QUALITY_PHOTO
    # 일러스트 스타일에 사진·렌즈 문구가 붙지 않는다 (같은 영상에서 그림체가 섞이던 원인)
    p = build_prompt("hands writing on a desk", "clean illustration style")
    assert "35mm" not in p and "photograph" not in p and "editorial illustration" in p


def test_fix_subject_fills_missing_gender():
    from app.image_prompt import fix_subject

    raw = "a Korean person in their 50s with short black hair, wearing a beige cardigan"
    assert fix_subject(raw, "50대 은퇴 주부", 1).startswith("a Korean woman in their 50s")
    assert fix_subject(raw, "30대 아빠", 0).startswith("a Korean man in their 50s")
    # 단서가 없으면 seed로 정하고, 같은 seed면 같은 결과
    assert fix_subject(raw, "50대 은퇴자", 7) == fix_subject(raw, "50대 은퇴자", 7)
    assert "person" not in fix_subject(raw, "50대 은퇴자", 7)
    # 이미 성별이 있으면 그대로
    ok = "a Korean woman in her early 30s with a low ponytail"
    assert fix_subject(ok, "30대 남성", 1) == ok


def test_apply_subject_rewrites_scene_prompts():
    from app.image_prompt import apply_subject

    raw = "a Korean person in their 50s with short black hair"
    fixed = "a Korean woman in their 50s with short black hair"
    assert apply_subject(f"{raw} sitting on a sofa", raw, fixed) == f"{fixed} sitting on a sofa"
    # 문구가 조금 달라도 성별 없는 'person'이면 성별을 넣는다
    assert apply_subject("a person holding a notebook", raw, fixed) == "a woman holding a notebook"
    assert (
        apply_subject("close-up of hands on a table", raw, fixed) == "close-up of hands on a table"
    )


def test_visual_style_choice_overrides_medium_but_keeps_light():
    from app.image_prompt import QUALITY_CINEMATIC, apply_visual_style, build_prompt

    llm = "clean illustration style, warm morning light, ivory background"
    style = apply_visual_style(llm, "cinematic")
    assert style.startswith("cinematic film look") and "illustration" not in style
    assert "warm morning light" in style and "ivory background" in style
    assert QUALITY_CINEMATIC in build_prompt("a man by the window", style)
    assert apply_visual_style(llm, "auto") == llm


async def test_visual_style_change_regenerates_only_from_s5(orch, store, sample_input):
    from app.schemas.project import StepState

    p = await orch.run_all(store.create(sample_input).id)
    before = [a.image.path for a in p.assets]
    p = await orch.edit(p.id, "input", p.input.model_copy(update={"visual_style": "watercolor"}))
    assert p.status["s4"] == StepState.DONE and p.status["s5"] == StepState.STALE
    p = await orch.run_step(p.id, "s5")
    assert all("watercolor" in a.image.prompt for a in p.assets)
    assert [a.image.path for a in p.assets] != before
