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
import logging
import time
import traceback
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.adapters.base import Adapters
from app.config import Settings
from app.events import EventBus
from app.metrics import LLM_CALLS, NULL_METRICS, Metrics
from app.readiness import not_ready as content_not_ready
from app.schemas.project import (
    STEP_IDS,
    Input,
    OutputKey,
    Project,
    StepId,
    StepLLMUsage,
    StepState,
)
from app.store import ProjectStore

StepFn = Callable[["StepContext"], Awaitable[Any]]

# 필드 단위 전파: 이 필드만 바뀌면 처음 읽는 단계부터만 stale로 만든다.
# 예) 사진(user_media)만 추가했는데 S2~S4(LLM·YouTube)까지 다시 돌릴 필요는 없다.
FIELD_FIRST_READER: dict[tuple[str, str], StepId] = {
    ("input", "user_media"): "s5",
    ("input", "visual_style"): "s5",
    ("input", "voice"): "s5",
}


log = logging.getLogger("app.orchestrator")


def describe_error(e: BaseException) -> str:
    """사용자에게 보여 줄 오류 문구. 메시지가 빈 예외는 발생 위치를 붙여 단서를 남긴다."""
    msg = str(e).strip()
    if not msg:
        tb = traceback.extract_tb(e.__traceback__)
        if tb:
            last = tb[-1]
            msg = f"(메시지 없음) {Path(last.filename).name}:{last.lineno} {last.name}"
    return f"{type(e).__name__}: {msg}"


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
        StepSpec("s7", ("input", "timeline"), "render", s7_render.run),
    )


class Orchestrator:
    def __init__(
        self,
        store: ProjectStore,
        adapters: Adapters,
        settings: Settings,
        bus: EventBus | None = None,
        pipeline: tuple[StepSpec, ...] | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self.store = store
        self.metrics = metrics or NULL_METRICS
        self.adapters = adapters
        self.settings = settings
        self.bus = bus or EventBus()
        self.pipeline = pipeline or _build_pipeline()
        self._specs = {s.id: s for s in self.pipeline}
        self._writer = {s.writes: s for s in self.pipeline}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._active: set[str] = set()  # start_*로 예약된 실행 (태스크 시작 전 이중 실행 방지)
        self._tasks: set[asyncio.Task] = set()

    # ── 공개 API ─────────────────────────────────────────

    def create_project(self, inp: Input | None) -> Project:
        project = self.store.create(inp)
        self.metrics.log("project_created", pid=project.id)
        return project

    def duplicate_project(self, project_id: str) -> Project:
        """A/B 변형 만들기 (F-W6). S1~S4(입력·레퍼런스·요인·전략)를 그대로 가져가고 S5~S7은 비운다.

        변형은 대사·제목을 바꿔 S5부터 다시 만드는 용도라 원본의 자산·렌더 파일은 복사하지 않는다.
        업로드한 사진(media/)은 S5가 다시 쓰므로 복사한다.
        """
        if self.is_busy(project_id):
            raise ProjectBusy(project_id)
        src = self.store.load(project_id)
        siblings = [r for r in self.store.list() if r.parent_id == project_id]
        keep = STEP_IDS[:4]
        copy = Project(
            id=self.store.new_id(),
            parent_id=project_id,
            variant=chr(ord("B") + len(siblings)),
            status={s: (src.status[s] if s in keep else StepState.IDLE) for s in STEP_IDS},
            warnings={s: w for s, w in src.warnings.items() if s in keep},
            errors={s: e for s, e in src.errors.items() if s in keep},
            input=src.input,
            refs=src.refs,
            factors=src.factors,
            strategy=src.strategy,
        )
        self.store.copy_media(project_id, copy.id)
        copy = self.store.save(copy)
        self.metrics.log("project_duplicated", pid=copy.id, parent=project_id)
        return copy

    async def restore_version(self, project_id: str, version: int) -> Project:
        """이전 버전으로 되돌린다 (F-W5). 되돌린 것도 새 버전으로 저장되므로 다시 되돌릴 수 있다.

        S5~S7은 파일(이미지·음성·영상)이 그 뒤에 덮어써졌을 수 있어, 완료 상태였다면 stale로 둔다.
        """
        if self.is_busy(project_id):
            raise ProjectBusy(project_id)
        current = self.store.load(project_id)
        snap = self.store.load_version(project_id, version)
        restored = snap.model_copy(update={"version": current.version})
        for s in STEP_IDS[4:]:
            if restored.status[s] == StepState.DONE:
                restored.status[s] = StepState.STALE
        restored = self.store.save(restored)
        self.metrics.log("version_restored", pid=project_id, version=version)
        await self.bus.publish(
            project_id, {"type": "edited", "key": "input", "version": restored.version}
        )
        return restored

    def delete_project(self, project_id: str) -> None:
        """프로젝트를 지운다. 실행 중이면 거절한다. 변형(B, C…)은 따로 남는다."""
        if self.is_busy(project_id):
            raise ProjectBusy(project_id)
        self.store.delete(project_id)
        self._locks.pop(project_id, None)
        self.metrics.log("project_deleted", pid=project_id)
        log.info("project deleted %s", project_id)

    def cleanup_project(self, project_id: str) -> dict:
        """어떤 버전도 쓰지 않는 자산 파일을 지운다. 실행 중이면 거절한다."""
        if self.is_busy(project_id):
            raise ProjectBusy(project_id)
        self.store.load(project_id)  # 없는 프로젝트면 ProjectNotFound
        out = self.store.cleanup(project_id)
        log.info("project cleanup %s %s", project_id, out)
        return out

    async def run_step(
        self, project_id: str, step_id: StepId, *, _reserved: bool = False
    ) -> Project:
        lock = self._lock(project_id, _reserved)
        async with lock:
            return await self._run(project_id, self._specs[step_id])

    async def run_all(
        self,
        project_id: str,
        from_step: StepId = "s1",
        *,
        to_step: StepId = "s7",
        _reserved: bool = False,
    ) -> Project:
        """from_step부터 to_step까지(기본 끝까지). 오류가 나면 그 단계에서 멈춘다.

        쉬운 화면은 아이디어를 넣으면 다듬기 직전(s6)까지만 자동으로 돌리고, 렌더는 '완성'에서 한다.
        """
        lock = self._lock(project_id, _reserved)
        async with lock:
            start = STEP_IDS.index(from_step)
            project = self.store.load(project_id)
            stop = STEP_IDS.index(to_step)
            for spec in self.pipeline[start : stop + 1]:
                # 앞 단계는 끝났지만 내용이 모자라면(예: 장면 이미지가 비어 있음)
                # 실패시키지 않고 멈춘다.
                # 이유는 GET /projects/{id}의 not_ready로 화면에 보인다
                if self.not_ready(project, spec.id):
                    break
                project = await self._run(project_id, spec)
                if project.status[spec.id] != StepState.DONE:
                    break
            await self.bus.publish(project_id, {"type": "run_finished", "version": project.version})
            return project

    def is_busy(self, project_id: str) -> bool:
        return project_id in self._active or self._locks[project_id].locked()

    def any_busy(self) -> bool:
        """실행 중인 프로젝트가 하나라도 있는가 (어댑터를 바꾸기 전에 확인)."""
        return bool(self._active) or any(lock.locked() for lock in self._locks.values())

    def start_run_step(self, project_id: str, step_id: StepId) -> asyncio.Task:
        """백그라운드 실행 (API용). 선행 조건·중복 실행은 여기서 바로 거절한다."""
        self._precheck(project_id, step_id)
        return self._spawn(project_id, self.run_step(project_id, step_id, _reserved=True))

    def start_run_all(
        self, project_id: str, from_step: StepId = "s1", to_step: StepId = "s7"
    ) -> asyncio.Task:
        self._precheck(project_id, from_step)
        return self._spawn(
            project_id, self.run_all(project_id, from_step, to_step=to_step, _reserved=True)
        )

    async def edit(self, project_id: str, key: OutputKey, value: Any) -> Project:
        """사용자 편집 (PATCH /projects/{id}/{key}). 해당 단계는 DONE, 뒤 단계는 stale.

        FIELD_FIRST_READER에 있는 필드만 바뀌었으면 그 필드를 처음 읽는 단계부터만 stale.
        """
        if self.is_busy(project_id):
            raise ProjectBusy(project_id)
        spec = self._writer[key]
        project = self.store.load(project_id)
        old = getattr(project, key)
        setattr(project, key, value)  # validate_assignment로 스키마 검증
        narrow = self._narrow_reader(key, old, getattr(project, key))
        if narrow:
            start = STEP_IDS.index(narrow)
            self._invalidate_downstream(project, STEP_IDS[start - 1])
        else:
            project.status[spec.id] = StepState.DONE
            project.errors.pop(spec.id, None)
            self._invalidate_downstream(project, spec.id)
        project = self.store.save(project)
        self.metrics.log("edited", pid=project_id, key=key)
        await self.bus.publish(
            project_id, {"type": "edited", "key": key, "version": project.version}
        )
        return project

    def not_ready(self, project: Project, step_id: StepId) -> str | None:
        """앞 단계는 끝났지만 내용이 모자라 이 단계가 반드시 실패할 이유 (app/readiness.py)."""
        if self.blockers(project, step_id):
            return None
        return content_not_ready(project, step_id, self.settings)

    def blockers(self, project: Project, step_id: StepId) -> list[StepId]:
        """step_id 실행 전에 DONE이어야 하는데 아직 아닌 앞 단계들."""
        spec = self._specs[step_id]
        needed = [self._writer[k].id for k in spec.reads]
        return [s for s in needed if project.status[s] != StepState.DONE]

    # ── 내부 ─────────────────────────────────────────────

    def _lock(self, project_id: str, reserved: bool = False) -> asyncio.Lock:
        lock = self._locks[project_id]
        if lock.locked() or (project_id in self._active and not reserved):
            raise ProjectBusy(project_id)
        return lock

    def _precheck(self, project_id: str, step_id: StepId) -> None:
        if self.is_busy(project_id):
            raise ProjectBusy(project_id)
        project = self.store.load(project_id)
        blocked = self.blockers(project, step_id)
        if blocked:
            raise StepBlocked(f"{step_id} 실행 전에 {', '.join(blocked)}를 완료해야 한다")
        reason = self.not_ready(project, step_id)
        if reason:
            raise StepBlocked(reason)

    def _spawn(self, project_id: str, coro) -> asyncio.Task:
        self._active.add(project_id)
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)

        def done(t: asyncio.Task) -> None:
            self._active.discard(project_id)
            self._tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                exc = t.exception()
                asyncio.get_running_loop().create_task(
                    self.bus.publish(project_id, {"type": "run_failed", "error": str(exc)})
                )

        task.add_done_callback(done)
        return task

    @staticmethod
    def _narrow_reader(key: str, old: Any, new: Any) -> StepId | None:
        if old is None or new is None or not hasattr(old, "model_dump"):
            return None
        before, after = old.model_dump(), new.model_dump()
        changed = {f for f in after if before.get(f) != after[f]}
        readers = {FIELD_FIRST_READER.get((key, f)) for f in changed}
        if changed and None not in readers and len(readers) == 1:
            return readers.pop()
        return None

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
        t0, units0 = time.perf_counter(), self._quota_used()
        calls_token = LLM_CALLS.set([])
        try:
            output = await spec.run(ctx)
            setattr(project, spec.writes, output)
        except Exception as e:  # 단계 실패는 상태로 기록하고 사용자에게 보여 준다
            calls = self._log_llm_calls(project_id, spec.id, calls_token)
            self._set_llm_usage(project, spec.id, calls)
            log.error("step %s failed (%s)", spec.id, project_id, exc_info=e)
            project.status[spec.id] = StepState.ERROR
            project.errors[spec.id] = describe_error(e)
            project = self.store.save(project)
            self.metrics.log(
                "step_error", pid=project_id, step=spec.id, error=type(e).__name__,
                sec=round(time.perf_counter() - t0, 2),
            )  # fmt: skip
            await self.bus.publish(
                project_id,
                {"type": "step_error", "step": spec.id, "error": project.errors[spec.id]},
            )
            return project

        calls = self._log_llm_calls(project_id, spec.id, calls_token)
        self._set_llm_usage(project, spec.id, calls)
        project.status[spec.id] = StepState.DONE
        # 어댑터가 남긴 알림(무료 한도 소진으로 모델·이미지 소스 대체 등)도 사용자에게 보인다
        for adapter in (self.adapters.llm, self.adapters.image):
            drain = getattr(adapter, "drain_notices", None)
            if drain:
                ctx.warnings.extend(drain())
        if ctx.warnings:
            project.warnings[spec.id] = ctx.warnings
        else:
            project.warnings.pop(spec.id, None)
        self._invalidate_downstream(project, spec.id)
        project = self.store.save(project)
        self._log_step_done(project, spec, time.perf_counter() - t0, units0)
        await self.bus.publish(
            project_id, {"type": "step_done", "step": spec.id, "version": project.version}
        )
        return project

    def _log_llm_calls(self, project_id: str, step_id: StepId, token) -> list[dict]:
        calls = LLM_CALLS.get() or []
        LLM_CALLS.reset(token)
        for call in calls:
            self.metrics.log("llm_call", pid=project_id, step=step_id, **call)
        return calls

    @staticmethod
    def _set_llm_usage(project: Project, step_id: StepId, calls: list[dict]) -> None:
        """이 단계를 어떤 모델이 처리했고 비용이 얼마인지 프로젝트에 남긴다 (화면 표시용)."""
        ok = [c for c in calls if c.get("ok")]
        if not ok:
            project.llm_usage.pop(step_id, None)
            return
        project.llm_usage[step_id] = StepLLMUsage(
            models=list(dict.fromkeys(c.get("model", "?") for c in ok)),
            providers=list(dict.fromkeys(c.get("provider", "?") for c in ok)),
            calls=len(calls),
            usd=round(sum(c.get("usd") or 0 for c in calls), 5),
        )

    def _quota_used(self) -> int | None:
        quota = getattr(self.adapters.youtube, "quota", None)
        return quota.used() if quota is not None else None

    def _log_step_done(self, project: Project, spec: StepSpec, sec: float, units0: int | None):
        fields: dict[str, Any] = {"sec": round(sec, 2)}
        if units0 is not None and spec.id in ("s2", "s3"):
            fields["units"] = (self._quota_used() or 0) - units0
        if spec.id == "s3" and project.factors is not None:
            fields["factors"] = len(project.factors)
            fields["with_evidence"] = sum(1 for f in project.factors if f.evidence)
        self.metrics.log("step_done", pid=project.id, step=spec.id, **fields)
        if spec.id == "s7" and project.render is not None:
            self.metrics.log(
                "render_done", pid=project.id, duration_sec=project.render.duration_sec
            )

    def _invalidate_downstream(self, project: Project, step_id: StepId) -> None:
        for spec in self.pipeline[STEP_IDS.index(step_id) + 1 :]:
            has_output = getattr(project, spec.writes) is not None
            project.status[spec.id] = StepState.STALE if has_output else StepState.IDLE
            project.errors.pop(spec.id, None)
