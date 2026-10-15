"""CLI 시나리오(PRD §5)와 S5 대본 정리·사진 순환, S6 LLM 연출·폴백."""

import pytest

from app import cli
from app.schemas.project import StepState
from app.steps.s5_prompts import tts_script

DONE, STALE = StepState.DONE, StepState.STALE


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


async def sf(capsys, *argv) -> tuple[int, str]:
    code = await cli.main(list(argv))
    return code, capsys.readouterr().out


def load(data_dir, pid):
    from app.store import ProjectStore

    return ProjectStore(data_dir).load(pid)


def statuses(p):
    return [p.status[s].value for s in ("s1", "s2", "s3", "s4", "s5", "s6", "s7")]


async def test_cli_scenario_edit_flow(data_dir, tmp_path, capsys):
    photo = tmp_path / "me.jpg"
    photo.write_bytes(b"\xff\xd8fake")

    code, out = await sf(
        capsys, "new", "퇴근 후 10분 홈트로 3개월간 바뀐 점", "--audience", "30대 직장인"
    )
    assert code == 0
    pid = out.strip()

    code, out = await sf(capsys, "run", pid, "--fake")
    assert code == 0
    assert "▶ s1" in out and "✔ s7 완료" in out and "MP4" in out
    assert "번호 선택" in out  # 전체 실행 후 레퍼런스 목록을 보여 준다

    # 시나리오 3: 레퍼런스를 고쳐 고르면 S3부터 재생성 필요
    code, _ = await sf(capsys, "select", pid, "2,3")
    p = load(data_dir, pid)
    assert [i for i, r in enumerate(p.refs, 1) if r.selected] == [2, 3]
    assert statuses(p) == ["done", "done"] + ["stale"] * 5

    # 막힌 단계는 실행 거부 (s3가 stale이라 s4 불가)
    with pytest.raises(cli.OrchestratorError):
        await cli.main(["run", pid, "--step", "s4", "--fake"])

    code, _ = await sf(capsys, "run", pid, "--from", "s3", "--fake")
    assert code == 0 and statuses(load(data_dir, pid)) == ["done"] * 7

    # 시나리오 5: 대사를 고치면 S5~S7 재생성 필요
    await sf(capsys, "set-line", pid, "S2", "퇴근하면 소파가 먼저였어요")
    p = load(data_dir, pid)
    assert p.strategy.scenes[1].line == "퇴근하면 소파가 먼저였어요"
    assert statuses(p) == ["done"] * 4 + ["stale"] * 3

    await sf(capsys, "run", pid, "--from", "s5", "--fake")
    # 시나리오 6: S3 장면을 본인 사진으로 교체하면 S6~S7 재생성 필요
    await sf(capsys, "set-photo", pid, "S3", str(photo))
    p = load(data_dir, pid)
    s3 = next(a for a in p.assets if a.scene_id == "S3")
    assert s3.image.source == "user" and s3.image.path == str(photo.resolve())
    assert statuses(p) == ["done"] * 5 + ["stale"] * 2

    code, out = await sf(capsys, "list")
    assert pid in out and "퇴근 후" in out


async def test_cli_rejects_bad_input(data_dir, capsys):
    with pytest.raises(cli.CLIError, match="사진을 찾을 수 없다"):
        await cli.main(["new", "주제", "--photos", "nope/none.jpg"])
    _, out = await sf(capsys, "new", "주제")
    pid = out.strip()
    with pytest.raises(cli.CLIError, match="레퍼런스가 없다"):
        await cli.main(["select", pid, "1"])


# ── S5 ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("line", "script"),
    [
        ("3개월 전엔 계단도 숨찼어요 😮‍💨 #홈트 #shorts", "3개월 전엔 계단도 숨찼어요."),
        ("(웃음) 오늘도 10분~ 같이 해요", "오늘도 10분 같이 해요."),
        ("지금은... 달라요!", "지금은… 달라요!"),
        ("[자막] 스쿼트, 플랭크, 런지", "스쿼트, 플랭크, 런지."),
    ],
)
def test_tts_script(line, script):
    assert tts_script(line) == script


async def test_s5_cycles_photos_when_images_not_generated(orch, store, adapters, sample_input):
    async def no_image(*args, **kwargs):
        return None

    adapters.image.generate = no_image
    sample_input.user_media = ["a.jpg", "b.jpg"]
    p = store.create(sample_input)
    p = await orch.run_all(p.id, from_step="s1")
    assert [a.image.path for a in p.assets] == ["a.jpg", "b.jpg", "a.jpg", "b.jpg", "a.jpg"]
    assert all(a.image.source == "user" for a in p.assets)
    assert any("같은 사진을 다시 썼다" in w for w in p.warnings["s5"])


async def test_s5_without_photos_blocks_at_s6(orch, store, adapters, sample_input):
    async def no_image(*args, **kwargs):
        return None

    adapters.image.generate = no_image
    p = await orch.run_all(store.create(sample_input).id)
    assert p.status["s5"] == DONE and p.status["s6"] == StepState.ERROR
    assert "이미지나 음성이 없는 장면" in p.errors["s6"]


async def test_s5_rejects_emoji_only_line(orch, store, adapters, sample_input):
    from app.adapters.fake import FakeLLM

    def s4(user):
        s = FakeLLM._s4_strategy(adapters.llm, user)
        s["scenes"][2]["line"] = "✨✨ #shorts"
        return s

    adapters.llm._s4_strategy = s4
    p = await orch.run_all(store.create(sample_input).id)
    assert p.status["s5"] == StepState.ERROR and "S3 대사가 비어 있다" in p.errors["s5"]


# ── S6 ────────────────────────────────────────────────────


async def test_s6_applies_llm_style_but_keeps_paths_and_first_cut(orch, store, sample_input):
    p = await orch.run_all(store.create(sample_input).id)
    tl = p.timeline
    assert [s.motion.type for s in tl.scenes] == [
        "zoom_in",
        "pan_right",
        "static",
        "zoom_out",
        "pan_left",
    ]
    assert tl.scenes[0].transition.type == "cut"  # 첫 장면에는 전환이 없다
    assert tl.scenes[1].transition.type == "slide"
    assert [s.image for s in tl.scenes] == [a.image.path for a in p.assets]
    assert [s.caption.text for s in tl.scenes] == [a.voice.text for a in p.assets]


async def test_s6_falls_back_to_rules_when_llm_fails(orch, store, adapters, sample_input):
    def broken(user):
        raise RuntimeError("down")

    adapters.llm._s6_timeline = broken
    p = await orch.run_all(store.create(sample_input).id)
    assert p.status["s6"] == DONE and p.status["s7"] == DONE
    assert p.timeline.scenes[1].motion.type == "pan_left"  # 규칙 기반 순환
    assert any("규칙 기반 연출" in w for w in p.warnings["s6"])
