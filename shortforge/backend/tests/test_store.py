import pytest

from app.store import ProjectNotFound


def test_create_save_load_versions(store, sample_input):
    p = store.create(sample_input)
    assert p.version == 1
    p.input.audience = "20대"
    p2 = store.save(p)
    assert p2.version == 2
    assert store.load(p.id).input.audience == "20대"
    assert store.versions(p.id) == [1, 2]
    assert store.load_version(p.id, 1).input.audience == "30대 직장인"


def test_transient_save_skips_snapshot(store, sample_input):
    p = store.create(sample_input)
    p = store.save(p, snapshot=False)
    assert p.version == 2
    assert store.load(p.id).version == 2
    assert store.versions(p.id) == [1]


def test_list_index(store, sample_input):
    a = store.create(sample_input)
    rows = store.list()
    assert [r.id for r in rows] == [a.id]
    assert rows[0].topic == sample_input.topic
    assert rows[0].stages == ",".join(["idle"] * 7) and rows[0].thumb is None


def test_list_summary_backfilled_for_old_db(store, sample_input):
    """요약 열이 없던 예전 DB도 다시 열면 project.json에서 진행 상태를 채운다."""
    from app.schemas.project import StepState
    from app.store import ProjectStore

    p = store.create(sample_input)
    p.status["s1"] = StepState.DONE
    store.save(p)
    with store.engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE projects DROP COLUMN thumb")
        conn.exec_driver_sql("ALTER TABLE projects DROP COLUMN stages")
    store.engine.dispose()

    again = ProjectStore(store.data_dir)
    assert again.list()[0].stages.split(",")[:2] == ["done", "idle"]


def test_missing_project(store):
    with pytest.raises(ProjectNotFound):
        store.load("prj_nope")


def test_partly_deleted_project_can_be_deleted_again(store, sample_input):
    p = store.create(sample_input)
    (store.project_dir(p.id) / "project.json").unlink()  # 잠긴 파일 때문에 일부만 지워진 상태
    store.delete(p.id)
    assert p.id not in [r.id for r in store.list()]
    with pytest.raises(ProjectNotFound):
        store.delete(p.id)
