"""FastAPI 엔트리 (PROJECT_PROMPT §8). 웹 UI와 CLI는 같은 오케스트레이터를 쓴다.

    uv run uvicorn app.main:app --port 8000

실행은 백그라운드 태스크로 돌고(202), 진행은 GET /projects/{id}/events(SSE)로 받는다.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError

from app.adapters.fake import FakeLLM
from app.adapters.registry import build_adapters
from app.config import Settings
from app.orchestrator import Orchestrator, ProjectBusy, StepBlocked
from app.quota import QuotaMeter
from app.schemas.project import STEP_IDS, Input, OutputKey, Project, StepId
from app.store import ProjectNotFound, ProjectStore

UPLOAD_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def is_image(data: bytes) -> bool:
    """확장자가 아니라 파일 시그니처로 JPEG/PNG/WEBP인지 본다."""
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SSE_HEARTBEAT_SEC = 15


def create_app(settings: Settings | None = None, orchestrator: Orchestrator | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if orchestrator is not None:
            app.state.orch = orchestrator
        else:
            store = ProjectStore(settings.data_dir)
            adapters = build_adapters(settings, fake_llm=settings.dev_fake_llm)
            app.state.orch = Orchestrator(store, adapters, settings)
        yield

    app = FastAPI(title="ShortForge", version="0.1.0", lifespan=lifespan)
    if orchestrator is not None:  # 테스트: lifespan 없이도 바로 쓸 수 있게
        app.state.orch = orchestrator
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def orch(request: Request) -> Orchestrator:
        return request.app.state.orch

    @app.exception_handler(ProjectNotFound)
    async def _nf(request, exc):
        return JSONResponse({"detail": f"프로젝트가 없다: {exc}"}, status_code=404)

    @app.exception_handler(ProjectBusy)
    async def _busy(request, exc):
        return JSONResponse({"detail": "이 프로젝트는 지금 실행 중이다"}, status_code=409)

    @app.exception_handler(StepBlocked)
    async def _blocked(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValidationError)
    async def _invalid(request, exc: ValidationError):
        return JSONResponse({"detail": json.loads(exc.json())}, status_code=422)

    # ── 상태 ────────────────────────────────────────────

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/config")
    def config(request: Request) -> dict:
        """UI 고지·배지용. 비밀값은 내보내지 않는다."""
        llm = orch(request).adapters.llm
        mode = "fake" if isinstance(llm, FakeLLM) else settings.llm_mode
        return {
            "llm_mode": mode,
            "llm_model": {"gemini": settings.gemini_model, "ollama": settings.ollama_model}.get(
                mode
            ),
            "image_mode": settings.image_mode,
            "tts_mode": settings.tts_mode,
            "tts_voice": settings.tts_voice,
            "render_preset": settings.render_preset,
            "free_tier_notice": mode == "gemini",
        }

    @app.get("/quota")
    def quota() -> dict:
        """오늘(PT 기준) YouTube units 사용량. 상단 쿼터 미터용 (F-2.4)."""
        return QuotaMeter(settings.db_path, settings.youtube_daily_unit_limit).summary()

    # ── 프로젝트 ─────────────────────────────────────────

    @app.get("/projects")
    def list_projects(request: Request) -> list[dict]:
        return [r.model_dump(mode="json") for r in orch(request).store.list()]

    @app.post("/projects", status_code=201)
    def create_project(request: Request, inp: Input) -> Project:
        return orch(request).store.create(inp)

    @app.get("/projects/{pid}")
    def get_project(request: Request, pid: str) -> dict:
        o = orch(request)
        p = o.store.load(pid)
        return {
            **p.model_dump(mode="json"),
            "busy": o.is_busy(pid),
            "blockers": {s: o.blockers(p, s) for s in STEP_IDS},
        }

    @app.patch("/projects/{pid}/{key}")
    async def edit(
        request: Request, pid: str, key: OutputKey, value: Annotated[Any, Body()]
    ) -> Project:
        return await orch(request).edit(pid, key, value)

    # 실행 엔드포인트는 async여야 한다.
    # 동기 함수는 스레드풀에서 돌아 이벤트 루프에 백그라운드 태스크를 만들 수 없다.
    @app.post("/projects/{pid}/steps/{step}/run", status_code=202)
    async def run_step(request: Request, pid: str, step: str) -> dict:
        sid = _step_id(step)
        orch(request).start_run_step(pid, sid)
        return {"started": sid}

    @app.post("/projects/{pid}/run-all", status_code=202)
    async def run_all(
        request: Request, pid: str, start: Annotated[str, Query(alias="from")] = "s1"
    ) -> dict:
        sid = _step_id(start)
        orch(request).start_run_all(pid, sid)
        return {"started": sid, "mode": "run-all"}

    @app.get("/projects/{pid}/events")
    async def events(request: Request, pid: str) -> StreamingResponse:
        o = orch(request)
        o.store.load(pid)  # 없는 프로젝트면 404
        q = o.bus.subscribe(pid)

        async def stream():
            try:
                yield "retry: 3000\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        e = await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_SEC)
                    except TimeoutError:
                        yield ": heartbeat\n\n"
                        continue
                    yield f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
            finally:
                o.bus.unsubscribe(pid, q)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── 파일 ────────────────────────────────────────────

    @app.post("/projects/{pid}/media", status_code=201)
    async def upload_media(
        request: Request,
        pid: str,
        files: Annotated[list[UploadFile], File()],
        attach: bool = True,
    ) -> dict:
        """사진 업로드. attach=True면 input.user_media에 추가(S5부터 재생성 필요).

        attach=False면 파일만 저장하고 경로를 돌려준다 — 장면 사진 교체(PATCH assets)용.
        """
        o = orch(request)
        p = o.store.load(pid)
        if p.input is None:
            raise HTTPException(400, "주제를 먼저 입력한다")
        media_dir = o.store.project_dir(pid) / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for f in files:
            ext = Path(f.filename or "").suffix.lower()
            if ext not in UPLOAD_EXT:
                raise HTTPException(415, f"지원하지 않는 형식: {f.filename} (jpg/png/webp)")
            data = await f.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"{f.filename}: 25MB를 넘는다")
            if not is_image(data):
                raise HTTPException(
                    415, f"{f.filename}: 이미지 파일이 아니다 (내용이 JPEG/PNG/WEBP가 아님)"
                )
            stem = re.sub(r"[^\w-]", "_", Path(f.filename or "photo").stem)[:40] or "photo"
            dest = media_dir / f"{stem}_{secrets.token_hex(3)}{ext}"
            dest.write_bytes(data)
            saved.append(dest.relative_to(o.store.project_dir(pid)).as_posix())
        if not attach:
            return {"saved": saved, "user_media": p.input.user_media}
        inp = p.input.model_copy(update={"user_media": [*p.input.user_media, *saved]})
        p = await o.edit(pid, "input", inp)
        return {"saved": saved, "user_media": p.input.user_media}

    @app.get("/projects/{pid}/files/{path:path}")
    def get_file(request: Request, pid: str, path: str, download: bool = False) -> FileResponse:
        """프로젝트 폴더 안의 파일만 내준다 (경로 탈출 차단).

        download=1이면 첨부 파일로 내준다 — 웹 UI와 API의 출처가 달라 <a download>가 무시되기 때문.
        """
        base = orch(request).store.project_dir(pid).resolve()
        target = (base / path).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise HTTPException(404, "파일이 없다")
        if download:
            return FileResponse(target, filename=f"shortforge_{pid}{target.suffix}")
        return FileResponse(target)

    return app


def _step_id(step: str) -> StepId:
    """'s3' 또는 '3' 모두 받는다."""
    sid = step if step.startswith("s") else f"s{step}"
    if sid not in STEP_IDS:
        raise HTTPException(404, f"단계가 없다: {step}")
    return sid  # type: ignore[return-value]


app = create_app()
