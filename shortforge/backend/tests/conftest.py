from __future__ import annotations

import pytest

from app.adapters.fake import fake_adapters
from app.config import Settings
from app.events import EventBus
from app.orchestrator import Orchestrator
from app.schemas.project import Input
from app.store import ProjectStore


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    """개발자 .env의 실제 키를 테스트가 쓰지 않게 덮어쓴다 (새 clone에서도 같은 결과)."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-dummy-youtube")
    monkeypatch.setenv("GEMINI_API_KEY", "test-dummy-gemini")
    monkeypatch.setenv("DEV_FAKE_LLM", "false")


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
