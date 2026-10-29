from app.adapters.tts.edge import SPEECH_TAIL, speech_length
from app.schemas.project import VoiceAsset


def test_speech_length_drops_trailing_silence():
    # 실측: 마지막 어절이 1.925초에 끝나는데 파일은 2.808초 (0.9초가 조용하다)
    words = [
        {"text": "안녕", "start": 0.1, "end": 0.8},
        {"text": "하세요", "start": 0.8, "end": 1.925},
    ]
    assert speech_length(words, 2.808) == round(1.925 + SPEECH_TAIL, 3)
    assert speech_length(words, 2.0) == 2.0  # 파일 길이를 넘지 않는다
    assert speech_length([], 2.808) is None


def test_voice_length_falls_back_to_file_length():
    old = VoiceAsset(text="a", voice="v", duration_sec=2.8)  # 예전 프로젝트
    assert old.length == 2.8
    assert VoiceAsset(text="a", voice="v", duration_sec=2.8, speech_sec=2.2).length == 2.2


async def test_scene_length_uses_speech_not_file(orch, store, adapters, sample_input):
    from app.schemas.project import LAST_SCENE_EXTRA_PAD

    adapters.tts.tail = 0.9  # 실제 Edge-TTS처럼 끝이 0.9초 조용하다
    p = orch.create_project(sample_input)
    for s in ("s1", "s2", "s3", "s4", "s5", "s6"):
        p = await orch.run_step(p.id, s)
    voices = {a.scene_id: a.voice for a in p.assets}
    for sc in p.timeline.scenes:
        v = voices[sc.id]
        assert v.speech_sec == round(v.duration_sec - 0.9, 2)
        assert sc.duration == round(v.speech_sec + sc.pad, 2)  # 파일 길이가 아니라 말 길이
    last = p.timeline.scenes[-1]
    assert last.pad == round(p.timeline.scenes[0].pad + LAST_SCENE_EXTRA_PAD, 2)


async def test_scene_photo_survives_look_change(orch, store, adapters, sample_input):
    """다듬기에서 장면에 올린 내 사진은 그림 느낌을 바꿔 5단계를 다시 해도 남는다."""
    p = orch.create_project(sample_input)
    for s in ("s1", "s2", "s3", "s4", "s5"):
        p = await orch.run_step(p.id, s)
    photo = "media/mine.jpg"
    (store.project_dir(p.id) / "media").mkdir(exist_ok=True)
    (store.project_dir(p.id) / photo).write_bytes(b"jpg")
    assets = [a.model_copy(deep=True) for a in p.assets]
    assets[1].image.source, assets[1].image.path = "user", photo
    await orch.edit(p.id, "assets", assets)
    inp = p.input.model_copy(update={"visual_style": "watercolor"})
    await orch.edit(p.id, "input", inp)
    p = await orch.run_step(p.id, "s5")
    kept = next(a for a in p.assets if a.scene_id == assets[1].scene_id)
    assert kept.image.path == photo and kept.image.source == "user"
    others = [a for a in p.assets if a.scene_id != assets[1].scene_id]
    drawn = [a for a in others if a.image.source == "generated"]
    assert drawn and all("watercolor" in a.image.prompt.lower() for a in drawn)
