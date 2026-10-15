"""단계 실행·의존성·stale 전파 (PROJECT_PROMPT §5).

규칙
- 각 단계는 선언한 reads 키만 읽고, writes 키 하나만 쓴다. 단계끼리 직접 호출하지 않는다.
- 단계 N을 실행하려면 reads 키를 쓰는 앞 단계가 모두 DONE이어야 한다.
- 단계 N의 출력이 바뀌면(실행 성공 또는 사용자 편집) 뒤 단계는
  출력이 있으면 STALE("재생성 필요"), 없으면 IDLE이 된다. 자동 재실행은 하지 않는다.
"""

from __future__ import annotations

import asyncio
import copy
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.adapters.base import Adapters
from app.config import Settings
from app.events import EventBus
from app.schemas.project import STEP_IDS, OutputKey, Project, StepId, StepState
from app.store import ProjectStore

StepFn = Callable[["StepContext"], Awaitable[Any]]


class OrchestratorError(Exception):
    pass


class StepBlocked(OrchestratorError):
    """선행 단계가 끝나지 않아 실행할 수 없다."""


class ProjectBusy(OrchestratorError):
    """같은 프로젝트에서 다른 실행이 진행 중이다."""


class ContractViolation(OrchestratorError):
    """단계가 선언하지 않은 키를 읽으려 했다."""


class StepInputError(OrchestratorError):
    """단계 입력이 실행 조건을 만족하지 않는다 (사용자에게 그대로 보여 줄 메시지)."""


@dataclass(frozen=True)
class StepSpec:
    id: StepId
    reads: tuple[OutputKey, ...]
    writes: OutputKey
    run: StepFn


@dataclass
class StepContext:
    """단계에 주어지는 유일한 창구. 계약에 없는 키는 읽을 수 없다."""

    spec: StepSpec
    _project: Project
    adapters: Adapters
    settings: Settings
    project_dir: Path
    _bus: EventBus
    warnings: list[str] = field(default_factory=list)

    def read(self, key: OutputKey) -> Any:
        if key not in self.spec.reads:
            raise ContractViolation(
                f"{self.spec.id}는 '{key}'를 읽을 수 없다 (reads={self.spec.reads})"
            )
        value = getattr(self._project, key)
        if value is None:
            raise StepInputError(f"'{key}'가 비어 있다")
        return copy.deepcopy(value)

    def current(self) -> Any:
        """자기 출력 키의 현재 값 (S1처럼 사용자 입력을 다듬는 단계용)."""
        return copy.deepcopy(getattr(self._project, self.spec.writes))

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    async def progress(self, stage: str, fraction: float) -> None:
        await self._bus.publish(
            self._project.id,
            {"type": "step_progress", "step": self.spec.id, "stage": stage, "progress": fraction},
        )


def _build_pipeline() -> tuple[StepSpec, ...]:
    from app.steps import (
        s1_input,
        s2_search,
        s3_factors,
        s4_strategy,
        s5_prompts,
        s6_timeline,
        s7_render,
    )

    return (
        StepSpec("s1", (), "input", s1_input.run),
        StepSpec("s2", ("input",), "refs", s2_search.run),
        StepSpec("s3", ("input", "refs"), "factors", s3_factors.run),
        StepSpec("s4", ("input", "factors", "refs"), "strategy", s4_strategy.run),
        StepSpec("s5", ("input", "strategy"), "assets", s5_prompts.run),
        StepSpec("s6", ("strategy", "assets"), "timeline", s6_timeline.run),
        StepSpec("s7", ("timeline",), "render", s7_render.run),
    )


class Orchestrator:
    def __init__(
        self,
        store: ProjectStore,
        adapters: Adapters,
        settings: Settings,
        bus: EventBus | None = None,
        pipeline: tuple[StepSpec, ...] | None = None,
    ) -> None:
        self.store = store
        self.adapters = adapters
        self.settings = settings
        self.bus = bus or EventBus()
        self.pipeline = pipeline or _build_pipeline()
        self._specs = {s.id: s for s in self.pipeline}
        self._writer = {s.writes: s for s in self.pipeline}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ── 공개 API ─────────────────────────────────────────

    async def run_step(self, project_id: str, step_id: StepId) -> Project:
        lock = self._lock(project_id)
        async with lock:
            return await self._run(project_id, self._specs[step_id])

    async def run_all(self, project_id: str, from_step: StepId = "s1") -> Project:
        """from_step부터 끝까지. 오류가 나면 그 단계에서 멈춘다."""
        lock = self._lock(project_id)
        async with lock:
            start = STEP_IDS.index(from_step)
            project = self.store.load(project_id)
            for spec in self.pipeline[start:]:
                project = await self._run(project_id, spec)
                if project.status[spec.id] != StepState.DONE:
                    break
            await self.bus.publish(project_id, {"type": "run_finished", "version": project.version})
            return project

    async def edit(self, project_id: str, key: OutputKey, value: Any) -> Project:
        """사용자 편집 (PATCH /projects/{id}/{key}). 해당 단계는 DONE, 뒤 단계는 stale."""
        if self._lock(project_id).locked():
            raise ProjectBusy(project_id)
        spec = self._writer[key]
        project = self.store.load(project_id)
        setattr(project, key, value)  # validate_assignment로 스키마 검증
        project.status[spec.id] = StepState.DONE
        project.errors.pop(spec.id, None)
        self._invalidate_downstream(project, spec.id)
        project = self.store.save(project)
        await self.bus.publish(
            project_id, {"type": "edited", "key": key, "version": project.version}
        )
        return project

    def blockers(self, project: Project, step_id: StepId) -> list[StepId]:
        """step_id 실행 전에 DONE이어야 하는데 아직 아닌 앞 단계들."""
        spec = self._specs[step_id]
        needed = [self._writer[k].id for k in spec.reads]
        return [s for s in needed if project.status[s] != StepState.DONE]

    # ── 내부 ─────────────────────────────────────────────

    def _lock(self, project_id: str) -> asyncio.Lock:
        lock = self._locks[project_id]
        if lock.locked():
            raise ProjectBusy(project_id)
        return lock

    async def _run(self, project_id: str, spec: StepSpec) -> Project:
        project = self.store.load(project_id)
        blocked = self.blockers(project, spec.id)
        if blocked:
            raise StepBlocked(f"{spec.id} 실행 전에 {', '.join(blocked)}를 완료해야 한다")

        project.status[spec.id] = StepState.RUNNING
        project.errors.pop(spec.id, None)
        project = self.store.save(project, snapshot=False)
        await self.bus.publish(project_id, {"type": "step_started", "step": spec.id})

        ctx = StepContext(
            spec=spec,
            _project=project,
            adapters=self.adapters,
            settings=self.settings,
            project_dir=self.store.project_dir(project_id),
            _bus=self.bus,
        )
        try:
            output = await spec.run(ctx)
            setattr(project, spec.writes, output)
        except Exception as e:  # 단계 실패는 상태로 기록하고 사용자에게 보여 준다
            project.status[spec.id] = StepState.ERROR
            project.errors[spec.id] = f"{type(e).__name__}: {e}"
            project = self.store.save(project)
            await self.bus.publish(
                project_id,
                {"type": "step_error", "step": spec.id, "error": project.errors[spec.id]},
            )
            return project

        project.status[spec.id] = StepState.DONE
        if ctx.warnings:
            project.warnings[spec.id] = ctx.warnings
        else:
            project.warnings.pop(spec.id, None)
        self._invalidate_downstream(project, spec.id)
        project = self.store.save(project)
        await self.bus.publish(
            project_id, {"type": "step_done", "step": spec.id, "version": project.version}
        )
        return project

    def _invalidate_downstream(self, project: Project, step_id: StepId) -> None:
        for spec in self.pipeline[STEP_IDS.index(step_id) + 1 :]:
            has_output = getattr(project, spec.writes) is not None
            project.status[spec.id] = StepState.STALE if has_output else StepState.IDLE
            project.errors.pop(spec.id, None)
