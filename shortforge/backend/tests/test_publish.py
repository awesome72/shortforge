"""업로드 전 체크리스트와 설명란 문구 (M2 · AI 고지)."""

from app.publish import hashtag, publish_kit


async def run(orch, store, sample_input):
    return await orch.run_all(store.create(sample_input).id)


def ids(kit):
    return [c["id"] for c in kit["checklist"]]


async def test_kit_reflects_generated_images_and_keywords(orch, store, sample_input):
    p = await run(orch, store, sample_input)  # Fake 이미지 = generated 5장
    kit = publish_kit(p)
    assert ids(kit) == ["synthetic", "references", "commercial"]
    assert "AI 생성 이미지 5장" in kit["checklist"][0]["text"]
    assert "업로드 화면에서 확인" in kit["checklist"][0]["text"]  # 정책을 단정하지 않는다
    lines = kit["description"].splitlines()
    assert lines[0] == p.strategy.titles[0]
    assert "AI 합성 음성(Microsoft Edge TTS), AI 생성 이미지(fake)" in kit["description"]
    assert lines[-1] == "#퇴근후홈트 #10분운동변화 #직장인운동루틴shorts #shorts"
    assert kit["counts"] == {"generated": 5, "stock": 0, "user": 0}


async def test_kit_adds_credits_and_portrait_items(orch, store, sample_input):
    sample_input.user_media = ["me.jpg"]
    p = await run(orch, store, sample_input)
    assets = [a.model_copy(deep=True) for a in p.assets]
    assets[1].image.source, assets[1].image.credit = (
        "stock",
        "Image by kim from Pixabay · https://x",
    )
    p = await orch.edit(p.id, "assets", assets)
    kit = publish_kit(p)
    assert "credits" in ids(kit) and "portrait" in ids(kit)
    assert "사진 출처:\n- Image by kim from Pixabay · https://x" in kit["description"]
    assert kit["counts"] == {"generated": 3, "stock": 1, "user": 1}


def test_hashtag_strips_spaces_and_symbols():
    assert hashtag("퇴근 후 홈트!") == "#퇴근후홈트"
