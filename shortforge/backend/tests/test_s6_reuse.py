"""목소리·그림 느낌만 바꿔 6단계를 다시 돌릴 때 연출 LLM을 다시 부르지 않는다."""

from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.main import create_app, download_name
from app.schemas.project import StepState


async def test_same_lines_reuse_direction(orch, adapters, sample_input):
    p = orch.create_project(sample_input)
    await orch.run_all(p.id, to_step="s6")
    first = orch.store.load(p.id).timeline
    assert first.direction_basis
    assert adapters.llm.calls.count("s6_timeline") == 1

    # 목소리만 바꾸면 5단계부터 다시 하지만 대사는 그대로다
    inp = orch.store.load(p.id).input.model_copy(update={"voice": "male"})
    await orch.edit(p.id, "input", inp)
    p = await orch.run_all(p.id, "s5", to_step="s6")
    assert p.status["s6"] == StepState.DONE
    assert adapters.llm.calls.count("s6_timeline") == 1
    again = p.timeline
    assert [s.motion for s in again.scenes] == [s.motion for s in first.scenes]
    assert [s.transition for s in again.scenes] == [s.transition for s in first.scenes]
    assert again.audio.mood == first.audio.mood


async def test_changed_line_asks_again(orch, adapters, sample_input):
    p = orch.create_project(sample_input)
    await orch.run_all(p.id, to_step="s6")
    strategy = orch.store.load(p.id).strategy
    scenes = [s.model_copy() for s in strategy.scenes]
    scenes[1] = scenes[1].model_copy(update={"line": "완전히 다른 대사로 바꿨어요"})
    await orch.edit(p.id, "strategy", strategy.model_copy(update={"scenes": scenes}))
    await orch.run_all(p.id, "s5", to_step="s6")
    assert adapters.llm.calls.count("s6_timeline") == 2


async def test_failed_direction_is_not_reused(orch, adapters, sample_input):
    original = adapters.llm.generate_json

    async def broken(task, *args, **kwargs):
        if task == "s6_timeline":
            raise RuntimeError("연출 실패")
        return await original(task, *args, **kwargs)

    adapters.llm.generate_json = broken
    p = orch.create_project(sample_input)
    p = await orch.run_all(p.id, to_step="s6")
    assert p.timeline.direction_basis == ""  # 규칙 연출은 다음에 다시 묻는다


@pytest.mark.parametrize(
    ("title", "path", "name"),
    [
        ("퇴근 후 10분: 홈트?", "render/final.mp4", "퇴근 후 10분 홈트.mp4"),
        ("퇴근 후 10분", "render/cover_ab12.jpg", "퇴근 후 10분_커버.jpg"),
        ("퇴근 후 10분", "assets/img/S1.png", "퇴근 후 10분_S1.png"),
        ("...", "render/final.srt", "shortforge_{pid}.srt"),
    ],
)
async def test_download_name(orch, sample_input, title, path, name):
    p = orch.create_project(sample_input)
    await orch.run_all(p.id, to_step="s4")
    strategy = orch.store.load(p.id).strategy
    await orch.edit(p.id, "strategy", strategy.model_copy(update={"titles": [title, "B안"]}))
    assert download_name(orch, p.id, Path(path)) == name.format(pid=p.id)


async def test_motion_needs_fresh_pictures(orch, sample_input):
    app = create_app(Settings(_env_file=None, data_dir=orch.store.data_dir), orch)
    p = orch.create_project(sample_input)
    await orch.run_all(p.id, to_step="s6")
    p = orch.store.load(p.id)
    p.status["s5"] = StepState.STALE
    orch.store.save(p, snapshot=False)

    class Never:
        async def generate(self, req):
            raise AssertionError("낡은 그림으로 영상을 만들면 안 된다")

    orch.adapters.video_gen = Never()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(f"/projects/{p.id}/scenes/{p.assets[0].scene_id}/motion")
    assert r.status_code == 409


async def test_reuse_follows_photo_and_video_swaps(orch, adapters, sample_input):
    p = orch.create_project(sample_input)
    await orch.run_all(p.id, to_step="s6")
    p = orch.store.load(p.id)
    clip = orch.store.project_dir(p.id) / "assets" / "video" / "S1_test.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"video")
    picture = p.assets[0].image

    assets = [a.model_copy(deep=True) for a in p.assets]
    assets[0].image = picture.model_copy(update={"path": "assets/video/S1_test.mp4"})
    await orch.edit(p.id, "assets", assets)
    p = await orch.run_step(p.id, "s6")
    assert p.timeline.scenes[0].motion.type == "static"  # 영상은 스스로 움직인다

    assets = [a.model_copy(deep=True) for a in p.assets]
    assets[0].image = picture
    await orch.edit(p.id, "assets", assets)
    p = await orch.run_step(p.id, "s6")
    assert p.timeline.scenes[0].motion.type == "zoom_in"  # 영상이던 장면은 규칙 움직임으로
    assert adapters.llm.calls.count("s6_timeline") == 1


async def test_partly_matched_direction_is_not_reused(orch, adapters, sample_input):
    original = adapters.llm.generate_json

    async def partial(task, *args, **kwargs):
        out = await original(task, *args, **kwargs)
        if task == "s6_timeline":
            out = out.model_copy(update={"scenes": out.scenes[:1]})
        return out

    adapters.llm.generate_json = partial
    p = orch.create_project(sample_input)
    p = await orch.run_all(p.id, to_step="s6")
    assert p.timeline.direction_basis == ""


def test_old_voices_use_word_timing_for_speech_length(tmp_path):
    """10-29 이전 음성은 말 길이 기록이 없다. 어절 타이밍으로 재 끝의 무음을 뺀다."""
    from app.schemas.project import VoiceAsset
    from app.steps.s6_timeline import voice_length

    words = '[{"text": "안녕", "start": 0.1, "end": 3.0}]'
    (tmp_path / "S1.words.json").write_text(words, encoding="utf-8")
    old = VoiceAsset(text="t", voice="v", duration_sec=3.9, words_path="S1.words.json")
    assert voice_length(old, tmp_path) == 3.25  # 마지막 어절 끝 + 0.25초
    new = old.model_copy(update={"speech_sec": 3.4})
    assert voice_length(new, tmp_path) == 3.4  # 기록이 있으면 그대로
    broken = old.model_copy(update={"words_path": "없음.json"})
    assert voice_length(broken, tmp_path) == 3.9  # 파일이 없으면 파일 길이
