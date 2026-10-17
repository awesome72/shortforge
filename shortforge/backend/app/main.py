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
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from app import __version__
from app.adapters.fake import FakeLLM
from app.adapters.registry import build_adapters
from app.config import Settings
from app.metrics import Metrics
from app.orchestrator import Orchestrator, ProjectBusy, StepBlocked
from app.publish import publish_kit
from app.quota import QuotaMeter
from app.schemas.project import STEP_IDS, ImageAsset, Input, OutputKey, Project, StepId
from app.steps.s5_prompts import fetch_image, image_stem
from app.store import ProjectNotFound, ProjectStore
from app.support import bundle, setup_logging

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
            setup_logging(settings)
            # 키가 비어 있어도 서버는 뜬다: 화면에서 무엇을 채울지 알려 준다
            app.state.setup_problems = problems = []
            adapters = build_adapters(settings, fake_llm=settings.dev_fake_llm, problems=problems)
            metrics = Metrics(settings.data_dir / "metrics.jsonl")
            app.state.orch = Orchestrator(store, adapters, settings, metrics=metrics)
        yield

    app = FastAPI(title="ShortForge", version=__version__, lifespan=lifespan)
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
            "image_sources": settings.image_sources,
            "tts_mode": settings.tts_mode,
            "tts_voice": settings.tts_voice,
            "render_preset": settings.render_preset,
            "free_tier_notice": mode == "gemini",
            "setup_problems": getattr(request.app.state, "setup_problems", []),
        }

    @app.get("/quota")
    def quota() -> dict:
        """오늘(PT 기준) YouTube units 사용량. 상단 쿼터 미터용 (F-2.4)."""
        out = QuotaMeter(settings.db_path, settings.youtube_daily_unit_limit).summary()
        if "cloudflare" in settings.image_sources:
            from app.adapters.image.cloudflare import NeuronMeter

            meter = NeuronMeter(settings.db_path, settings.cloudflare_daily_neurons)
            out["images"] = meter.summary()  # Cloudflare Neurons (00:00 UTC 초기화)
        return out

    # ── 프로젝트 ─────────────────────────────────────────

    @app.get("/projects")
    def list_projects(request: Request) -> list[dict]:
        return [r.model_dump(mode="json") for r in orch(request).store.list()]

    @app.post("/projects", status_code=201)
    def create_project(request: Request, inp: Input) -> Project:
        return orch(request).create_project(inp)

    @app.get("/projects/{pid}")
    def get_project(request: Request, pid: str) -> dict:
        o = orch(request)
        p = o.store.load(pid)
        return {
            **p.model_dump(mode="json"),
            "busy": o.is_busy(pid),
            "blockers": {s: o.blockers(p, s) for s in STEP_IDS},
        }

    @app.post("/projects/{pid}/duplicate", status_code=201)
    def duplicate(request: Request, pid: str) -> Project:
        """A/B 변형 만들기 (F-W6): S1~S4를 복사한 새 프로젝트."""
        return orch(request).duplicate_project(pid)

    @app.delete("/projects/{pid}", status_code=204)
    def delete_project(request: Request, pid: str) -> Response:
        """프로젝트와 그 파일을 모두 지운다. 되돌릴 수 없다. 변형(B, C…)은 남는다."""
        orch(request).delete_project(pid)
        return Response(status_code=204)

    @app.post("/projects/{pid}/cleanup")
    def cleanup(request: Request, pid: str) -> dict:
        """어떤 버전도 쓰지 않는 이미지·음성 파일(고르지 않은 후보 등)을 지운다."""
        return orch(request).cleanup_project(pid)

    @app.get("/support/bundle")
    def support_bundle(request: Request, project: str | None = None) -> Response:
        """문제 보고용 zip: 로그·환경 정보·사용 통계(+고른 프로젝트). 비밀값은 지운다."""
        o = orch(request)
        pdir = None
        if project:
            o.store.load(project)  # 없는 프로젝트면 404
            pdir = o.store.project_dir(project)
        problems = getattr(request.app.state, "setup_problems", [])
        name = f"shortforge-report-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
        return Response(
            bundle(settings, problems, pdir),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/projects/{pid}/versions")
    def versions(request: Request, pid: str, limit: int = 30) -> list[dict]:
        return orch(request).store.version_summaries(pid, limit=min(limit, 200))

    @app.post("/projects/{pid}/versions/{version}/restore")
    async def restore(request: Request, pid: str, version: int) -> Project:
        """이전 버전으로 되돌린다 (F-W5). 없는 버전이면 404."""
        return await orch(request).restore_version(pid, version)

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

    @app.post("/projects/{pid}/scenes/{scene_id}/image")
    async def regenerate_image(request: Request, pid: str, scene_id: str) -> dict:
        """장면 이미지 하나만 다시 만든다(seed+1 → 다른 그림). 바뀌면 S6부터 재생성 필요."""
        o = orch(request)
        if o.is_busy(pid):
            raise ProjectBusy(pid)
        p = o.store.load(pid)
        adapter = o.adapters.image
        if not adapter.wants_english_prompts:
            raise HTTPException(
                400, "IMAGE_MODE=upload에서는 이미지를 만들지 않는다 — 사진을 올린다"
            )
        assets = [a.model_copy(deep=True) for a in p.assets or []]
        target = next((a for a in assets if a.scene_id == scene_id), None)
        if target is None:
            raise HTTPException(404, f"장면이 없다: {scene_id} — 5단계를 먼저 실행한다")
        image = target.image
        image.seed += 1
        pdir = o.store.project_dir(pid)
        ok = await fetch_image(adapter, image, pdir / "assets" / image_stem(scene_id, image), pdir)
        drain = getattr(adapter, "drain_notices", None)
        notices = drain() if drain else []
        if not ok:
            raise HTTPException(502, "이미지를 얻지 못했다. " + " ".join(notices))
        p = await o.edit(pid, "assets", assets)
        return {"project": p.model_dump(mode="json"), "notices": notices}

    @app.post("/projects/{pid}/scenes/{scene_id}/candidates")
    async def image_candidates(request: Request, pid: str, scene_id: str, n: int = 3) -> dict:
        """장면 이미지 후보 n장(seed+1…+n)을 만든다 (F-5.4).

        적용하지 않는다 — 사용자가 고르면 select로 적용한다.
        """
        o = orch(request)
        p = o.store.load(pid)
        adapter = o.adapters.image
        if not adapter.wants_english_prompts:
            raise HTTPException(400, "IMAGE_MODE=upload에서는 이미지를 만들지 않는다")
        target = next((a for a in p.assets or [] if a.scene_id == scene_id), None)
        if target is None:
            raise HTTPException(404, f"장면이 없다: {scene_id} — 5단계를 먼저 실행한다")
        pdir = o.store.project_dir(pid)
        cand_dir = pdir / "assets" / "candidates"
        images = []
        for k in range(1, min(n, 4) + 1):
            img = target.image.model_copy(deep=True)
            img.seed = target.image.seed + k
            images.append(img)
        oks = await asyncio.gather(
            *(
                fetch_image(adapter, img, cand_dir / image_stem(scene_id, img), pdir)
                for img in images
            )
        )
        drain = getattr(adapter, "drain_notices", None)
        notices = drain() if drain else []
        found = [img.model_dump(mode="json") for img, ok in zip(images, oks, strict=True) if ok]
        if not found:
            raise HTTPException(502, "후보 이미지를 얻지 못했다. " + " ".join(notices))
        return {"candidates": found, "notices": notices}

    @app.post("/projects/{pid}/scenes/{scene_id}/image/select")
    async def select_candidate(
        request: Request, pid: str, scene_id: str, candidate: ImageAsset
    ) -> Project:
        """후보 하나를 장면 이미지로 적용한다. 경로는 이 프로젝트의 후보 폴더 안이어야 한다."""
        o = orch(request)
        p = o.store.load(pid)
        assets = [a.model_copy(deep=True) for a in p.assets or []]
        target = next((a for a in assets if a.scene_id == scene_id), None)
        if target is None:
            raise HTTPException(404, f"장면이 없다: {scene_id}")
        base = o.store.project_dir(pid).resolve()
        path = (base / (candidate.path or "")).resolve()
        if not path.is_relative_to(base / "assets" / "candidates") or not path.is_file():
            raise HTTPException(400, "후보 이미지 경로가 올바르지 않다")
        # 프롬프트·negative·검색어는 그대로 두고, 후보가 바꾸는 값만 받는다
        target.image.path = path.relative_to(base).as_posix()
        target.image.seed = candidate.seed
        target.image.source = candidate.source
        target.image.provider = candidate.provider
        target.image.credit = candidate.credit
        return await o.edit(pid, "assets", assets)

    @app.get("/projects/{pid}/publish")
    def publish(request: Request, pid: str) -> dict:
        """업로드 전 체크리스트와 YouTube 설명란 문구 (AI 고지·사진 출처·해시태그)."""
        return publish_kit(orch(request).store.load(pid))

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
            kind = target.suffix.lstrip(".")
            orch(request).metrics.log("download", pid=pid, kind=kind)
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
