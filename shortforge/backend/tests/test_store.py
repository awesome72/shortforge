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


def test_missing_project(store):
    with pytest.raises(ProjectNotFound):
        store.load("prj_nope")
