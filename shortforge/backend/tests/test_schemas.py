import pytest
from pydantic import ValidationError

from app.schemas.project import Factor, Project, Scene, StepState, Strategy


def test_new_project_all_idle():
    p = Project(id="prj_x")
    assert set(p.status) == {"s1", "s2", "s3", "s4", "s5", "s6", "s7"}
    assert all(s == StepState.IDLE for s in p.status.values())


def test_factor_requires_evidence():
    with pytest.raises(ValidationError):
        Factor(name="hook", finding="x", evidence=[], confidence="estimated")


def test_factor_evidence_format():
    with pytest.raises(ValidationError):
        Factor(name="title", finding="x", evidence=["no_field"], confidence="confirmed")
    f = Factor(name="title", finding="x", evidence=["abc:snippet.title"], confidence="confirmed")
    assert f.evidence == ["abc:snippet.title"]


def test_scene_end_after_start():
    with pytest.raises(ValidationError):
        Scene(id="S1", role="hook", start=2, end=2, line="", visual="")


def test_strategy_scene_count_and_titles():
    scene = {"id": "S1", "role": "hook", "start": 0, "end": 2, "line": "", "visual": ""}
    base = {"post_time_hint": "", "differentiator": "", "style_seed": ""}
    with pytest.raises(ValidationError):
        Strategy(titles=["A", "B"], scenes=[scene] * 4, **base)
    with pytest.raises(ValidationError):
        Strategy(titles=["A"], scenes=[scene] * 5, **base)


def test_unknown_keys_rejected():
    with pytest.raises(ValidationError):
        Project.model_validate({"id": "prj_x", "surprise": 1})


def test_json_roundtrip_and_schema_export():
    p = Project(id="prj_x")
    assert Project.model_validate_json(p.model_dump_json()) == p
    schema = Project.model_json_schema()
    assert "Timeline" in schema["$defs"]
