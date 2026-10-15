from __future__ import annotations

import pytest

from app.adapters.fake import fake_adapters
from app.config import Settings
from app.events import EventBus
from app.orchestrator import Orchestrator
from app.schemas.project import Input
from app.store import ProjectStore


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "data")


@pytest.fixture
def adapters():
    return fake_adapters()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def orch(store, adapters, bus) -> Orchestrator:
    settings = Settings(_env_file=None, data_dir=store.data_dir)
    return Orchestrator(store, adapters, settings, bus)


@pytest.fixture
def sample_input() -> Input:
    return Input(
        topic="퇴근 후 10분 홈트로  3개월간 바뀐 점",
        audience="30대 직장인",
        tone="empathetic",
        duration_sec=30,
    )
