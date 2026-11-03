"""실행 중인 작업 멈추기: 단계는 '멈췄어요'(이전 출력 유지), FFmpeg 같은 외부 프로그램도 꺼진다."""

import asyncio
import sys
import time

import httpx

from app.config import Settings
from app.main import create_app
from app.media import run
from app.orchestrator import CANCELLED
from app.schemas.project import StepState


async def test_cancel_keeps_previous_output_and_can_run_again(orch, store, adapters, sample_input):
    p = orch.create_project(sample_input)
    p = await orch.run_all(p.id)
    before = orch.store.load(p.id).refs

    gate = asyncio.Event()
    original = adapters.youtube.search

    async def slow_search(*args, **kwargs):
        await gate.wait()  # 멈추기 전까지 끝나지 않는다
        return await original(*args, **kwargs)

    adapters.youtube.search = slow_search
    task = orch.start_run_all(p.id, "s2", "s7")
    await asyncio.sleep(0.05)
    assert store.load(p.id).status["s2"] == StepState.RUNNING
    assert orch.cancel(p.id) is True
    await asyncio.gather(task, return_exceptions=True)

    p = store.load(p.id)
    assert p.status["s2"] == StepState.ERROR
    assert p.errors["s2"] == CANCELLED and p.error_kinds["s2"] == "cancelled"
    assert p.refs == before  # 이전 출력은 그대로
    assert not orch.is_busy(p.id) and orch.cancel(p.id) is False

    adapters.youtube.search = original
    p = await orch.run_all(p.id, "s2")
    assert p.status["s7"] == StepState.DONE  # 다시 실행할 수 있다


async def test_cancel_api(orch, store, sample_input):
    app = create_app(Settings(_env_file=None, data_dir=store.data_dir), orch)
    p = orch.create_project(sample_input)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(f"/projects/{p.id}/cancel")
        assert r.status_code == 200 and r.json() == {"cancelled": False}  # 멈출 것이 없다
        assert (await c.post("/projects/prj_000000000000/cancel")).status_code == 404


async def test_cancelled_run_stops_the_external_program(tmp_path):
    marker = tmp_path / "beat.txt"
    script = (
        "import time,sys\n"
        "for i in range(300):\n"
        "    open(sys.argv[1],'a').write('x'); time.sleep(0.1)\n"
    )
    task = asyncio.create_task(run([sys.executable, "-c", script, str(marker)]))
    await asyncio.sleep(1.0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    time.sleep(1.0)  # 감시 스레드가 끄는 시간
    size = marker.stat().st_size
    time.sleep(1.0)
    assert marker.stat().st_size == size  # 더 이상 쓰지 않는다 (프로그램이 꺼졌다)


async def test_stopping_voices_midway_asks_to_redo_later_steps(orch, store, adapters, sample_input):
    """5단계는 음성을 같은 이름에 덮어쓴다. 중간에 멈추면 6·7단계와 어긋나 다시 하게 한다."""
    p = orch.create_project(sample_input)
    await orch.run_all(p.id)
    gate = asyncio.Event()
    original = adapters.tts.synthesize

    async def slow(*args, **kwargs):
        await gate.wait()
        return await original(*args, **kwargs)

    adapters.tts.synthesize = slow
    app = create_app(Settings(_env_file=None, data_dir=store.data_dir), orch)
    task = orch.start_run_all(p.id, "s5", "s6")
    await asyncio.sleep(0.05)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(f"/projects/{p.id}/cancel")
    assert r.json() == {"cancelled": True}
    await asyncio.gather(task, return_exceptions=True)
    p = store.load(p.id)
    assert p.error_kinds["s5"] == "cancelled"
    assert p.status["s6"] == StepState.STALE and p.status["s7"] == StepState.STALE
