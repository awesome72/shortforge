"""다듬는 동안 장면 클립 미리 만들기: 켰을 때만, 편집이 멈춘 뒤, 렌더와 겹치지 않게."""

import asyncio

import pytest

import app.orchestrator as orchestrator
from app.schemas.project import StepState


@pytest.fixture
def calls(adapters, monkeypatch):
    monkeypatch.setattr(orchestrator, "PRERENDER_DELAY_SEC", 0.02)
    seen: list = []

    async def prepare(timeline, project_dir, should_stop):
        seen.append(should_stop())
        return 0

    adapters.video.prepare_clips = prepare
    return seen


async def ready(orch, store, sample_input):
    p = orch.create_project(sample_input)
    for s in ("s1", "s2", "s3", "s4", "s5", "s6"):
        p = await orch.run_step(p.id, s)
    return p


async def settle(orch):
    while orch._prerender_tasks:
        await asyncio.gather(*orch._prerender_tasks.values())
        await asyncio.sleep(0)


async def test_off_by_default(orch, store, sample_input, calls):
    await ready(orch, store, sample_input)
    assert not orch._prerender_tasks and calls == []


async def test_runs_once_after_edits_stop(orch, store, sample_input, calls):
    orch.settings.prerender_clips = True
    p = await ready(orch, store, sample_input)
    for text in ("한 번 고친 대사", "두 번 고친 대사"):
        strategy = p.strategy.model_copy(deep=True)
        strategy.scenes[0].line = text
        p = await orch.edit(p.id, "strategy", strategy)  # 편집마다 계획을 미룬다
    # 대사를 고치면 6단계가 '재생성 필요'라 만들 클립이 없다
    await settle(orch)
    assert calls == []

    p = await orch.run_step(p.id, "s5")
    p = await orch.run_step(p.id, "s6")
    await settle(orch)
    assert calls == [False]  # 편집이 멈춘 뒤 한 번


async def test_stops_when_busy(orch, store, sample_input, calls, monkeypatch):
    orch.settings.prerender_clips = True
    p = await ready(orch, store, sample_input)
    monkeypatch.setattr(orch, "any_busy", lambda: True)
    await settle(orch)
    assert calls == []  # 렌더·다른 편집이 돌면 시작하지 않는다
    assert p.status["s6"] == StepState.DONE


async def test_stops_for_other_projects_and_when_switched_off(orch, store, sample_input, calls):
    orch.settings.prerender_clips = True
    gen = orch._prerender_gen["prj_000000000000"]
    assert orch._prerender_should_stop("prj_000000000000", gen) is False
    orch._active.add("prj_111111111111")  # 다른 프로젝트가 렌더 중
    assert orch._prerender_should_stop("prj_000000000000", gen) is True
    orch._active.clear()
    orch.settings.prerender_clips = False
    assert orch._prerender_should_stop("prj_000000000000", gen) is True


async def test_delete_stops_prerender_first(orch, store, adapters, sample_input, monkeypatch):
    monkeypatch.setattr(orchestrator, "PRERENDER_DELAY_SEC", 0.01)
    orch.settings.prerender_clips = True
    started, finished = asyncio.Event(), []

    async def prepare(timeline, project_dir, should_stop):
        started.set()
        while not should_stop():
            await asyncio.sleep(0.01)
        finished.append(True)
        return 0

    adapters.video.prepare_clips = prepare
    p = await ready(orch, store, sample_input)
    orch.schedule_prerender(p.id)  # 단계가 잠금을 푼 뒤에 다시 잡는다 (지연이 아주 짧아서)
    await asyncio.wait_for(started.wait(), 5)
    # 삭제는 스레드풀에서 돈다 (동기 API)
    await asyncio.to_thread(orch.delete_project, p.id)
    assert finished  # 지우기 전에 멈췄다
    await asyncio.wait_for(settle(orch), 5)  # 지우는 동안 다시 시작하지 않는다
    assert not orch._prerender_closed
    assert not (store.project_dir(p.id)).exists()


async def test_failure_does_not_escape(orch, store, adapters, sample_input, calls):
    orch.settings.prerender_clips = True

    async def broken(*a):
        raise OSError("디스크")

    adapters.video.prepare_clips = broken
    await ready(orch, store, sample_input)
    await settle(orch)  # 예외가 새지 않는다 (렌더가 대신 만든다)
