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
