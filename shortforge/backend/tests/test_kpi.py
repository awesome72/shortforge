"""KPI 계측 (Step 9-4): 이벤트가 남는지, 집계가 PRD 정의대로인지."""

from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.kpi import compute
from app.metrics import Metrics
from app.orchestrator import Orchestrator

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)  # 월요일


def ev(minutes, event, pid, **kw):
    return {"ts": (T0 + timedelta(minutes=minutes)).isoformat(), "event": event, "pid": pid, **kw}


def by_name(kpis):
    return {k.name: k for k in kpis}


def test_compute_matches_prd_definitions():
    rows = [
        # A: 12분 만에 렌더, 다운로드, 전략 수정 후 다시 렌더 (재생성)
        ev(0, "project_created", "A"),
        ev(1, "step_done", "A", step="s2", units=303),
        ev(2, "step_done", "A", step="s3", units=4, factors=5, with_evidence=5),
        ev(12, "render_done", "A"),
        ev(13, "download", "A", kind="mp4"),
        ev(20, "edited", "A", key="strategy"),
        ev(22, "render_done", "A"),
        # B: 20분 만에 렌더했지만 다운로드 안 함
        ev(0, "project_created", "B"),
        ev(1, "step_done", "B", step="s2", units=0),
        ev(2, "step_done", "B", step="s3", units=4, factors=4, with_evidence=3),
        ev(20, "render_done", "B"),
        # C: 생성만 함
        ev(5, "project_created", "C"),
    ]
    kpis, weekly = compute(rows)
    k = by_name(kpis)
    assert round(k["완주율"].value, 1) == 33.3 and k["완주율"].grade() == "비관 수준"
    assert k["1편 제작 시간"].value == 16.0 and k["1편 제작 시간"].grade() == "비관 수준"
    assert k["재생성 비율"].value == 50.0 and k["재생성 비율"].grade() == "낙관 달성"
    assert round(k["근거 커버리지"].value, 1) == 88.9
    assert k["프로젝트당 쿼터"].value == 155.5 and k["프로젝트당 쿼터"].grade() == "낙관 달성"
    assert weekly == {"2026-W42": 1}


def test_empty_log():
    kpis, weekly = compute([])
    assert all(k.value is None and k.grade() == "데이터 없음" for k in kpis)
    assert weekly == {}


async def test_orchestrator_emits_events(store, adapters, sample_input, tmp_path):
    metrics = Metrics(tmp_path / "metrics.jsonl")
    orch = Orchestrator(store, adapters, Settings(_env_file=None), metrics=metrics)
    p = orch.create_project(sample_input)
    await orch.run_all(p.id)
    p = store.load(p.id)
    await orch.edit(p.id, "strategy", p.strategy)
    rows = metrics.read()
    events = [r["event"] for r in rows]
    assert events[0] == "project_created"
    assert events.count("step_done") == 7 and "render_done" in events and events[-1] == "edited"
    s3 = next(r for r in rows if r["event"] == "step_done" and r["step"] == "s3")
    assert s3["factors"] == s3["with_evidence"] == 3
    assert all(r["pid"] == p.id for r in rows)


def test_metrics_skips_broken_lines(tmp_path):
    path = tmp_path / "m.jsonl"
    m = Metrics(path)
    m.log("project_created", pid="x")
    with path.open("a", encoding="utf-8") as f:
        f.write('{"ts": "2026-10-1')  # 쓰다 끊긴 줄
    assert [r["event"] for r in m.read()] == ["project_created"]
