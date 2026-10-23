"""배경음악: 분위기 합성(app/music.py), S6 연결, 화면용 API(분위기·다른 곡·끄기·내 음악)."""

from pathlib import Path

import httpx
import pytest

from app import music
from app.config import Settings
from app.main import create_app, is_audio
from app.media import MediaError, find_exe
from app.publish import publish_kit

try:
    FFMPEG = find_exe("ffmpeg")
except MediaError:
    FFMPEG = None

MP3 = b"ID3\x04\x00fake-mp3"


@pytest.fixture
def app(orch, store):
    return create_app(Settings(_env_file=None, data_dir=store.data_dir), orch)


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def done_project(orch, sample_input):
    p = orch.create_project(sample_input)
    await orch.run_all(p.id)
    return orch.store.load(p.id)


def test_synth_is_deterministic_and_bounded():
    a = music.synth("upbeat", 2.0, seed=3)
    assert a == music.synth("upbeat", 2.0, seed=3)
    assert a != music.synth("upbeat", 2.0, seed=4)
    assert len(a) >= 2 * music.SR and max(abs(x) for x in a) <= 1.0
    # 모든 분위기가 만들어진다 (모르는 이름은 기본 분위기)
    for mood in [*music.MOODS, "unknown"]:
        assert music.synth(mood, 0.5, seed=1)


@pytest.mark.skipif(FFMPEG is None, reason="FFmpeg 없음")
async def test_render_bgm_writes_audio(tmp_path):
    out = tmp_path / music.bgm_filename("calm", 3, 1)
    await music.render_bgm(out, "calm", 3.0, 1)
    assert out.stat().st_size > 1000


async def test_s6_picks_mood_and_makes_bgm(orch, sample_input):
    p = await done_project(orch, sample_input)
    a = p.timeline.audio
    assert a.source == "generated" and a.mood == "warm" and not a.locked  # FakeLLM의 mood
    assert a.bgm.startswith("assets/music/bgm_warm_")
    assert (orch.store.project_dir(p.id) / a.bgm).exists()
    # 다시 실행해도 같은 곡(같은 파일)
    await orch.run_step(p.id, "s6")
    assert orch.store.load(p.id).timeline.audio.bgm == a.bgm


async def test_s6_without_music_when_off(store, adapters, bus, sample_input):
    from app.orchestrator import Orchestrator

    settings = Settings(_env_file=None, data_dir=store.data_dir, bgm_mode="off")
    o = Orchestrator(store, adapters, settings, bus)
    p = await done_project(o, sample_input)
    assert p.timeline.audio.bgm is None and p.timeline.audio.source is None


async def test_s6_failure_to_make_music_only_warns(orch, adapters, sample_input):
    async def broken(*_a, **_k):
        raise MediaError("ffmpeg 없음")

    adapters.video.make_bgm = broken
    p = await done_project(orch, sample_input)
    assert p.status["s7"] == "done" and p.timeline.audio.bgm is None
    assert any("배경음악" in w for w in p.warnings["s6"])


async def test_music_api_change_mood_another_off_and_auto(client, orch, sample_input):
    p = await done_project(orch, sample_input)
    url = f"/projects/{p.id}/music"

    r = await client.post(url, json={"mood": "tense"})
    assert r.status_code == 200
    a = r.json()["timeline"]["audio"]
    assert a["mood"] == "tense" and a["locked"] and a["bgm"].startswith("assets/music/bgm_tense_")
    assert r.json()["status"]["s7"] == "stale"  # 음악이 바뀌면 다시 렌더

    first = a["bgm"]
    a = (await client.post(url, json={"another": True})).json()["timeline"]["audio"]
    assert a["variant"] == 1 and a["bgm"] != first

    a = (await client.post(url, json={"gain_db": -22})).json()["timeline"]["audio"]
    assert a["bgm_gain_db"] == -22 and a["bgm"]  # 음량만 바꾸면 곡은 그대로

    # 사용자가 고른 음악은 6단계를 다시 실행해도 유지된다
    await orch.run_step(p.id, "s6")
    assert orch.store.load(p.id).timeline.audio.mood == "tense"

    a = (await client.post(url, json={"off": True})).json()["timeline"]["audio"]
    assert a["bgm"] is None and a["locked"]
    await orch.run_step(p.id, "s6")
    assert orch.store.load(p.id).timeline.audio.bgm is None  # 끈 상태도 유지

    a = (await client.post(url, json={"auto": True})).json()["timeline"]["audio"]
    assert not a["locked"]
    await orch.run_step(p.id, "s6")
    assert orch.store.load(p.id).timeline.audio.mood == "warm"  # 다시 내용에 맞춰 고른다

    assert (await client.post(url, json={"mood": "disco"})).status_code == 400
    assert (await client.post(url, json={"gain_db": 0})).status_code == 422


async def test_music_api_needs_timeline(client, orch, sample_input):
    p = orch.create_project(sample_input)
    r = await client.post(f"/projects/{p.id}/music", json={"mood": "calm"})
    assert r.status_code == 409


async def test_upload_own_music_and_publish_checklist(client, orch, sample_input):
    p = await done_project(orch, sample_input)
    url = f"/projects/{p.id}/music/upload"
    r = await client.post(url, files={"file": ("my song.mp3", MP3, "audio/mpeg")})
    assert r.status_code == 200, r.text
    a = r.json()["timeline"]["audio"]
    assert a["source"] == "user" and a["bgm"].startswith("media/my_song_") and a["mood"] is None
    assert (orch.store.project_dir(p.id) / a["bgm"]).read_bytes() == MP3

    kit = publish_kit(orch.store.load(p.id))
    assert any(c["id"] == "music" for c in kit["checklist"])

    bad = await client.post(url, files={"file": ("x.mp3", b"not audio", "audio/mpeg")})
    assert bad.status_code == 415
    bad = await client.post(url, files={"file": ("x.flac", MP3, "audio/flac")})
    assert bad.status_code == 415


async def test_publish_kit_mentions_generated_music(orch, sample_input):
    p = await done_project(orch, sample_input)
    kit = publish_kit(p)
    assert "배경음악(ShortForge가 직접 합성한 곡)을 사용해" in kit["description"]
    assert not any(c["id"] == "music" for c in kit["checklist"])


def test_is_audio_signatures():
    assert is_audio(MP3)
    assert is_audio(b"\xff\xfb\x90\x00")
    assert is_audio(b"\x00\x00\x00\x20ftypM4A ")
    assert is_audio(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    assert not is_audio(b"\x89PNG\r\n\x1a\n")
    assert not is_audio(b"RIFF\x00\x00\x00\x00WEBP")


def test_mood_names_match_everywhere():
    prompt = (Path(__file__).parents[1] / "app/prompts/s6_timeline.md").read_text("utf-8")
    for mood in music.MOOD_LABEL:
        assert mood in prompt
