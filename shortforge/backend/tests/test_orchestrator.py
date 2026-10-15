import asyncio

import pytest

from app.orchestrator import (
    ContractViolation,
    Orchestrator,
    ProjectBusy,
    StepBlocked,
    StepSpec,
)
from app.schemas.project import STEP_IDS, StepState

DONE, STALE, IDLE, ERROR = StepState.DONE, StepState.STALE, StepState.IDLE, StepState.ERROR


def statuses(p):
    return [p.status[s] for s in STEP_IDS]


async def test_run_all_with_fakes_completes_pipeline(orch, store, sample_input):
    p = store.create(sample_input)
    p = await orch.run_all(p.id)

    assert statuses(p) == [DONE] * 7, p.errors
    assert p.input.topic == "퇴근 후 10분 홈트로 3개월간 바뀐 점"  # 공백 정규화
    assert 3 <= len(p.input.keywords) <= 5
    assert len(p.refs) <= 10 and sum(r.selected for r in p.refs) == 4
    assert all(r.duration_sec <= 60 for r in p.refs)
    assert len(p.strategy.scenes) == 5
    assert [a.scene_id for a in p.assets] == [s.id for s in p.strategy.scenes]
    assert p.render.path == "render/final.mp4"
    assert p.render.duration_sec == pytest.approx(sum(s.duration for s in p.timeline.scenes))


async def test_s3_drops_factor_without_valid_evidence(orch, store, sample_input):
    p = await orch.run_all(store.create(sample_input).id)
    selected = {r.video_id for r in p.refs if r.selected}
    assert all(e.split(":")[0] in selected for f in p.factors for e in f.evidence)
    assert "empathy" not in {f.name for f in p.factors}  # FakeLLM이 넣은 근거 없는 요인
    assert any("근거가 없는 요인" in w for w in p.warnings["s3"])
    hook = next(f for f in p.factors if f.name == "hook")
    assert hook.confidence == "estimated"


async def test_rerun_marks_downstream_stale(orch, store, sample_input):
    p = await orch.run_all(store.create(sample_input).id)
    p = await orch.run_step(p.id, "s2")
    assert statuses(p) == [DONE, DONE] + [STALE] * 5


async def test_edit_marks_writer_done_and_downstream_stale(orch, store, sample_input):
    p = await orch.run_all(store.create(sample_input).id)
    strategy = p.strategy.model_copy(deep=True)
    strategy.scenes[1].line = "사용자가 고친 대사"
    p = await orch.edit(p.id, "strategy", strategy)

    assert statuses(p) == [DONE] * 4 + [STALE] * 3
    assert p.strategy.scenes[1].line == "사용자가 고친 대사"


async def test_edit_accepts_plain_dict_and_validates(orch, store, sample_input):
    p = await orch.run_all(store.create(sample_input).id)
    refs = [r.model_dump(mode="json") for r in p.refs]
    for r in refs:
        r["selected"] = False
    refs[0]["selected"] = True
    p = await orch.edit(p.id, "refs", refs)
    assert sum(r.selected for r in p.refs) == 1
    assert statuses(p)[2:] == [STALE] * 5

    with pytest.raises(ValueError):
        await orch.edit(p.id, "refs", [{"video_id": "missing fields"}])


async def test_downstream_without_output_stays_idle(orch, store, sample_input):
    p = store.create(sample_input)
    await orch.run_step(p.id, "s1")
    p = await orch.run_step(p.id, "s2")
    p = await orch.run_step(p.id, "s1")
    assert statuses(p) == [DONE, STALE, IDLE, IDLE, IDLE, IDLE, IDLE]


async def test_blocked_until_upstream_done(orch, store, sample_input):
    p = store.create(sample_input)
    with pytest.raises(StepBlocked):
        await orch.run_step(p.id, "s3")

    p = await orch.run_all(p.id)
    await orch.run_step(p.id, "s2")  # s3 이후 stale
    with pytest.raises(StepBlocked):
        await orch.run_step(p.id, "s4")  # s3가 stale이므로 막힌다
    p = await orch.run_all(p.id, from_step="s3")
    assert statuses(p) == [DONE] * 7


async def test_step_error_is_recorded_and_stops_run_all(orch, store):
    p = store.create(None)  # 주제 없음 → s1 실패
    p = await orch.run_all(p.id)
    assert p.status["s1"] == ERROR
    assert "주제" in p.errors["s1"]
    assert statuses(p)[1:] == [IDLE] * 6


async def test_error_cleared_after_successful_rerun(orch, store, sample_input):
    p = await orch.run_all(store.create(sample_input).id)
    orch.adapters.llm._s4_strategy = lambda user: {"broken": True}
    p = await orch.run_step(p.id, "s4")
    assert p.status["s4"] == ERROR
    assert p.strategy is not None  # 실패해도 이전 출력은 보존

    del orch.adapters.llm._s4_strategy
    p = await orch.run_step(p.id, "s4")
    assert p.status["s4"] == DONE and "s4" not in p.errors


async def test_contract_violation_on_undeclared_read(store, adapters, sample_input):
    async def sneaky(ctx):
        return ctx.read("factors")  # s2는 factors를 읽을 수 없다

    from app.config import Settings

    pipeline = list(Orchestrator(store, adapters, Settings(_env_file=None)).pipeline)
    pipeline[1] = StepSpec("s2", ("input",), "refs", sneaky)
    orch = Orchestrator(store, adapters, Settings(_env_file=None), pipeline=tuple(pipeline))
    p = store.create(sample_input)
    await orch.run_step(p.id, "s1")
    p = await orch.run_step(p.id, "s2")
    assert p.status["s2"] == ERROR
    assert ContractViolation.__name__ in p.errors["s2"]


async def test_concurrent_run_rejected(orch, store, adapters, sample_input):
    gate = asyncio.Event()
    original = adapters.youtube.search

    async def slow_search(*args, **kwargs):
        await gate.wait()  # S2 실행 중에 멈춰 둔다
        return await original(*args, **kwargs)

    adapters.youtube.search = slow_search
    p = store.create(sample_input)
    task = asyncio.create_task(orch.run_all(p.id))
    await asyncio.sleep(0.05)
    assert store.load(p.id).status["s2"] == StepState.RUNNING
    with pytest.raises(ProjectBusy):
        await orch.run_step(p.id, "s1")
    with pytest.raises(ProjectBusy):
        await orch.edit(p.id, "input", sample_input)
    gate.set()
    p = await task
    assert statuses(p) == [DONE] * 7


async def test_events_published_in_order(orch, store, bus, sample_input):
    p = store.create(sample_input)
    q = bus.subscribe(p.id)
    await orch.run_all(p.id)
    events = []
    while not q.empty():
        events.append(q.get_nowait())

    lifecycle = [(e["type"], e.get("step")) for e in events if e["type"] != "step_progress"]
    expected = [(t, s) for s in STEP_IDS for t in ("step_started", "step_done")]
    assert lifecycle == expected + [("run_finished", None)]
    assert any(e["type"] == "step_progress" and e["step"] == "s7" for e in events)


async def test_partial_rerun_from_step(orch, store, adapters, sample_input):
    p = await orch.run_all(store.create(sample_input).id)
    calls_before = list(adapters.llm.calls)
    p = await orch.run_all(p.id, from_step="s4")
    assert statuses(p) == [DONE] * 7
    # s1~s3은 다시 돌지 않는다 (s6는 연출을 고르느라 LLM을 부른다)
    assert adapters.llm.calls[len(calls_before) :] == ["s4_strategy", "s6_timeline"]
