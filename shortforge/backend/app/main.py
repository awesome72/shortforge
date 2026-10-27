"""FastAPI 엔트리 (PROJECT_PROMPT §8). 웹 UI와 CLI는 같은 오케스트레이터를 쓴다.

    uv run uvicorn app.main:app --port 8000

실행은 백그라운드 태스크로 돌고(202), 진행은 GET /projects/{id}/events(SSE)로 받는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from app import __version__
from app import keys as keystore
from app.adapters.base import ImageQuotaExceeded
from app.adapters.fake import FakeLLM
from app.adapters.image.pixabay_video import preview
from app.adapters.llm.routed import RoutedLLM
from app.adapters.registry import build_adapters, pixabay_video
from app.config import ENV_FILE, Settings
from app.image_prompt import has_person
from app.media import VIDEO_EXT, MediaError
from app.metrics import Metrics
from app.music import MOOD_LABEL, ensure_bgm
from app.orchestrator import Orchestrator, ProjectBusy, StepBlocked
from app.publish import cover_path, cover_title, publish_kit, save_cover_title
from app.quota import QuotaMeter
from app.readiness import unused_image_sources
from app.schemas.project import STEP_IDS, ImageAsset, Input, OutputKey, Project, StepId, Timeline
from app.steps.s5_prompts import fetch_image, image_stem
from app.steps.s7_render import RENDER_QUALITY, rendered_quality
from app.store import ProjectNotFound, ProjectStore
from app.support import bundle, setup_logging

log = logging.getLogger("app.api")


class MusicIn(BaseModel):
    """6단계 배경음악 바꾸기. 하나만 보낸다 (gain_db는 다른 것과 함께 보내도 된다)."""

    mood: str | None = None  # 이 분위기로 새로 합성 (app.music.MOOD_LABEL의 키)
    another: bool = False  # 같은 분위기의 다른 곡
    off: bool = False  # 음악 끄기
    auto: bool = False  # 고정 해제: 다음 6단계 실행 때 다시 내용에 맞춰 고른다
    gain_db: float | None = Field(default=None, ge=-30, le=-6)


MUSIC_EXT = {".mp3", ".m4a", ".wav"}


def is_audio(data: bytes) -> bool:
    """확장자가 아니라 파일 시그니처로 MP3/M4A/WAV인지 본다."""
    return (
        data.startswith(b"ID3")
        or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)  # MP3 프레임 동기
        or data[4:8] == b"ftyp"
        or (data[:4] == b"RIFF" and data[8:12] == b"WAVE")
    )


class CoverIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)  # 커버 문구 ("/"는 줄바꿈)


class VideoPick(BaseModel):
    id: int  # Pixabay 동영상 ID (미리보기 목록의 id)
    focus_x: float | None = Field(default=None, ge=0, le=1)  # 썸네일 판정의 피사체 위치


class BrandIn(BaseModel):
    name: str = Field(default="", max_length=30)


class AdvancedIn(BaseModel):
    mode: Literal["off", "anthropic", "openai", "openrouter"]
    model: str = ""
    effort: Literal["low", "medium", "high"] = "medium"
    daily_budget_usd: float = Field(default=1.0, ge=0.1, le=100.0)
    accept_cost: bool = False


UPLOAD_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def is_image(data: bytes) -> bool:
    """확장자가 아니라 파일 시그니처로 JPEG/PNG/WEBP인지 본다."""
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )


def is_video(data: bytes) -> bool:
    """MP4·MOV(ftyp 상자)·WEBM(EBML 머리)인지 파일 시그니처로 본다."""
    return data[4:8] == b"ftyp" or data.startswith(b"\x1a\x45\xdf\xa3")


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 300 * 1024 * 1024  # 장면 동영상 (30초 1080p는 보통 20~60MB)
UPLOAD_CHUNK = 1024 * 1024
SSE_HEARTBEAT_SEC = 15


def create_app(
    settings: Settings | None = None,
    orchestrator: Orchestrator | None = None,
    env_path: Path | None = None,
):
    settings = settings or Settings()
    env_path = env_path or ENV_FILE

    def rebuild(app: FastAPI):
        """설정으로 어댑터를 다시 만든다 (시작할 때, 화면에서 키를 저장했을 때)."""
        app.state.setup_problems = problems = []
        return build_adapters(
            settings,
            fake=settings.dev_fake_all,
            fake_llm=settings.dev_fake_llm,
            problems=problems,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if orchestrator is not None:
            app.state.orch = orchestrator
        else:
            store = ProjectStore(settings.data_dir)
            setup_logging(settings)
            # 키가 비어 있어도 서버는 뜬다: 화면에서 무엇을 채울지 알려 준다
            app.state.rebuild = rebuild
            adapters = rebuild(app)
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
            "stock_video": bool(settings.pixabay_api_key),  # 5단계 '영상 후보' (Pixabay)
            "tts_mode": settings.tts_mode,
            "tts_voice": settings.tts_voice,
            "render_preset": settings.render_preset,
            "brand_name": settings.brand_name,
            "free_tier_notice": mode == "gemini",
            "setup_problems": getattr(request.app.state, "setup_problems", []),
            "advanced": advanced_info(llm),
            # 키는 있는데 이미지 방식에 들어 있지 않은 소스 (설정 불일치 안내)
            "image_unused": unused_image_sources(settings),
        }

    def advanced_info(llm) -> dict | None:
        """고급 모드(D13)가 실제로 켜져 있을 때만: 모델·작업·오늘 사용액 (배지용)."""
        if not isinstance(llm, RoutedLLM):
            return None
        return {
            "provider": settings.llm_advanced,
            "model": llm.advanced.model,
            "label": llm.label,
            "tasks": sorted(llm.tasks),
            **llm.spend.summary(),
        }

    # ── 키 설정 (화면에서 .env 편집 대신) ─────────────────

    def same_origin_only(request: Request) -> None:
        # 서버는 127.0.0.1에만 뜨지만 다른 사이트의 페이지도 브라우저로 localhost에 POST할 수 있다.
        # 브라우저는 교차 출처 POST에 Origin을 붙이므로 웹 UI 출처가 아니면 막는다.
        origin = request.headers.get("origin")
        if origin and origin not in settings.cors_origins:
            raise HTTPException(403, "웹 UI에서만 키를 바꿀 수 있다")
        if "application/json" not in request.headers.get("content-type", ""):
            raise HTTPException(415, "JSON으로 보낸다")

    @app.get("/settings/keys")
    def key_status() -> dict:
        """키가 들어 있는지만 알려 준다. 값은 내보내지 않는다."""
        return keystore.status(settings)

    @app.post("/settings/keys/check")
    async def key_check(request: Request, values: Annotated[dict[str, str], Body()]) -> dict:
        """저장하지 않고 무료 호출로 키를 확인한다."""
        same_origin_only(request)
        try:
            clean = keystore.validate(values)
        except keystore.KeyInputError as e:
            raise HTTPException(422, str(e)) from e
        transport = getattr(request.app.state, "key_transport", None)
        anthropic_client = getattr(request.app.state, "anthropic_http_client", None)
        return {"results": await keystore.check(clean, settings, transport, anthropic_client)}

    @app.post("/settings/keys")
    async def key_save(
        request: Request,
        values: Annotated[dict[str, str], Body(embed=True)],
        image_mode: Annotated[str | None, Body(embed=True)] = None,
    ) -> dict:
        """확인을 통과한 키를 .env에 저장하고, 서버를 다시 시작하지 않고 바로 쓴다.

        확인에서 거절된 키(잘못된 키, 결제가 연결된 Gemini 키)는 저장하지 않는다.
        응답을 받지 못한 경우(네트워크)는 저장하고 그 사실을 알려 준다.
        """
        same_origin_only(request)
        o = orch(request)
        if o.any_busy():
            raise HTTPException(409, "실행 중인 단계가 끝난 뒤 저장한다")
        try:
            clean = keystore.validate(values)
        except keystore.KeyInputError as e:
            raise HTTPException(422, str(e)) from e
        if image_mode is not None and image_mode not in keystore.IMAGE_MODES:
            raise HTTPException(422, f"고를 수 없는 이미지 방식: {image_mode}")
        transport = getattr(request.app.state, "key_transport", None)
        anthropic_client = getattr(request.app.state, "anthropic_http_client", None)
        results = await keystore.check(clean, settings, transport, anthropic_client)
        rejected = [n for n, r in results.items() if r["ok"] is False]
        if rejected:
            return JSONResponse({"saved": [], "results": results}, status_code=422)
        updates = dict(clean)
        if image_mode is not None:
            updates["IMAGE_MODE"] = image_mode
        if updates:
            keystore.write_env(env_path, updates)
            keystore.apply(settings, clean, image_mode)
        rebuild_fn = getattr(request.app.state, "rebuild", None)
        if rebuild_fn is not None:
            o.adapters = rebuild_fn(request.app)
        log.info("키 설정 저장: %s", ", ".join(sorted(updates)) or "(없음)")
        return {
            "saved": sorted(updates),
            "results": results,
            "setup_problems": getattr(request.app.state, "setup_problems", []),
        }

    @app.post("/settings/brand")
    async def brand_save(request: Request, body: BrandIn) -> dict:
        """엔딩 카드의 채널 이름을 .env에 저장한다 (비우면 엔딩 카드 없음).

        다시 렌더하면 반영된다.
        """
        same_origin_only(request)
        o = orch(request)
        if o.any_busy():
            raise HTTPException(409, "실행 중인 단계가 끝난 뒤 저장한다")
        name = re.sub(r"[\r\n{}\\]", "", body.name).strip()
        keystore.write_env(env_path, {"BRAND_NAME": name})
        settings.brand_name = name
        rebuild_fn = getattr(request.app.state, "rebuild", None)
        if rebuild_fn is not None:
            o.adapters = rebuild_fn(request.app)
        return {"brand_name": name}

    @app.post("/settings/advanced")
    async def advanced_save(request: Request, body: AdvancedIn) -> dict:
        """고급 모드(D13, 유료)를 켜거나 끈다. 켤 때는 과금 동의와 키가 필요하다."""
        from app.spend import DEFAULT_MODEL, PROVIDER_LABEL, price_for

        same_origin_only(request)
        o = orch(request)
        if o.any_busy():
            raise HTTPException(409, "실행 중인 단계가 끝난 뒤 저장한다")
        if body.mode == "off":  # 끌 때는 고른 모델·깊이·예산을 그대로 두고 스위치만 내린다
            keystore.write_env(env_path, {"LLM_ADVANCED": "off"})
            settings.llm_advanced = "off"
        model = body.model or DEFAULT_MODEL.get(body.mode, "")
        if body.mode != "off":
            if not body.accept_cost:
                raise HTTPException(422, "고급 모드는 과금될 수 있다는 안내에 동의해야 켤 수 있다")
            if not getattr(settings, f"{body.mode}_api_key"):
                name = PROVIDER_LABEL[body.mode]
                raise HTTPException(422, f"먼저 {name} API 키를 넣고 확인한다")
            if price_for(body.mode, model) is None:
                raise HTTPException(422, f"고를 수 없는 모델: {model}")
            keystore.write_env(
                env_path,
                keystore.advanced_updates(body.mode, model, body.effort, body.daily_budget_usd),
            )
            keystore.apply_advanced(settings, body.mode, model, body.effort, body.daily_budget_usd)
        rebuild_fn = getattr(request.app.state, "rebuild", None)
        if rebuild_fn is not None:
            o.adapters = rebuild_fn(request.app)
        log.info("고급 모드 설정: %s %s", body.mode, model or "-")
        return {
            "advanced": keystore.advanced_status(settings),
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

    # ── 예전 방식 영상 한꺼번에 다시 렌더 (LLM 없이 7단계만, 한 개씩 차례로) ──

    def outdated_ids(o: Orchestrator) -> list[str]:
        out = []
        for row in o.store.list():
            try:
                p = o.store.load(row.id)
            except Exception:  # noqa: BLE001 - 깨진 프로젝트 하나가 목록을 막지 않게
                continue
            if (
                p.render
                and p.status["s7"] == "done"
                and not o.is_busy(row.id)
                and rendered_quality(o.store.project_dir(row.id), p.render) < RENDER_QUALITY
            ):
                out.append(row.id)
        return out

    bulk: dict[str, Any] = {"running": False, "total": 0, "done": 0, "failed": 0}

    @app.get("/renders/outdated")
    def renders_outdated(request: Request) -> dict:
        """예전 방식(자막·색 보정·엔딩 카드 이전)으로 렌더한 프로젝트와 일괄 다시 렌더 진행 상황."""
        return {"ids": [] if bulk["running"] else outdated_ids(orch(request)), "bulk": bulk}

    @app.post("/renders/outdated/rerender", status_code=202)
    async def rerender_outdated(request: Request) -> dict:
        """예전 방식 영상을 차례로 다시 렌더한다. 동시에 돌리면 RAM 8GB PC가 버티지 못한다."""
        if bulk["running"]:
            raise HTTPException(409, "이미 다시 렌더하고 있어요")
        o = orch(request)
        ids = outdated_ids(o)
        bulk.update(running=bool(ids), total=len(ids), done=0, failed=0)

        async def work() -> None:
            try:
                for pid in ids:
                    try:
                        p = await o.run_step(pid, "s7")
                        failed = p.status["s7"] != "done"
                    except Exception:  # noqa: BLE001 - 하나가 실패해도 나머지는 계속
                        log.exception("일괄 다시 렌더 실패")
                        failed = True
                    bulk["done"] += 1
                    bulk["failed"] += int(failed)
            finally:
                bulk["running"] = False

        if ids:
            task = asyncio.create_task(work())
            request.app.state.bulk_task = task  # 태스크가 수거되지 않게 잡아 둔다
        return {"started": len(ids)}

    @app.get("/projects/{pid}")
    def get_project(request: Request, pid: str) -> dict:
        o = orch(request)
        p = o.store.load(pid)
        return {
            **p.model_dump(mode="json"),
            "busy": o.is_busy(pid),
            "blockers": {s: o.blockers(p, s) for s in STEP_IDS},
            # 앞 단계는 끝났지만 내용이 모자라 실행해도 실패할 단계와 그 해결 방법
            "not_ready": {s: r for s in STEP_IDS if (r := o.not_ready(p, s))},
            # 예전 방식(자막·색 보정·엔딩 카드 이전)으로 렌더한 영상이면 다시 렌더를 권한다
            "render_outdated": bool(p.render)
            and rendered_quality(o.store.project_dir(pid), p.render) < RENDER_QUALITY,
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

    def _video_source(o: Orchestrator):
        if not settings.pixabay_api_key:
            raise HTTPException(400, "동영상 후보에는 Pixabay 키가 필요해요 (설정 → API 키)")
        # 사람이 나와도 사용자가 고른다. video_transport는 테스트의 가짜 Pixabay 서버
        source = pixabay_video(
            settings, skip_person=False, transport=getattr(app.state, "video_transport", None)
        )
        source.llm = o.adapters.llm
        return source

    def _scene_asset(p: Project, scene_id: str):
        target = next((a for a in p.assets or [] if a.scene_id == scene_id), None)
        if target is None:
            raise HTTPException(404, f"장면이 없다: {scene_id} — 5단계를 먼저 실행한다")
        return target

    @app.post("/projects/{pid}/scenes/{scene_id}/videos")
    async def video_previews(request: Request, pid: str, scene_id: str, n: int = 6) -> dict:
        """무료 동영상 후보 미리보기 (D15). 검색·판정만 하고 내려받지 않는다.

        미리보기는 Pixabay의 작은 영상 주소라 화면이 바로 재생한다. 고르면 video/select가 받는다.
        """
        o = orch(request)
        target = _scene_asset(o.store.load(pid), scene_id)
        source = _video_source(o)
        query = target.image.query or target.image.prompt
        try:
            hits = await source.candidates(
                query, target.image.prompt, person=has_person(target.image.prompt)
            )
        except ImageQuotaExceeded as e:
            raise HTTPException(429, f"Pixabay 요청 한도에 걸렸어요. 1분 뒤에 다시 ({e})") from e
        except RuntimeError as e:
            raise HTTPException(502, f"무료 동영상을 찾지 못했어요: {e}") from e
        return {"query": query, "videos": [preview(h) for h in hits[: max(1, min(n, 12))]]}

    @app.post("/projects/{pid}/scenes/{scene_id}/video/select")
    async def select_video(request: Request, pid: str, scene_id: str, body: VideoPick) -> Project:
        """고른 무료 동영상을 받아 세로로 바꾼 뒤 장면에 적용한다 (6단계부터 재생성 필요)."""
        o = orch(request)
        p = o.store.load(pid)
        target = _scene_asset(p, scene_id)
        source = _video_source(o)
        hit = await source.find(target.image.query or target.image.prompt, body.id)
        if hit is None:
            raise HTTPException(
                404, "이 장면의 검색 결과에 없는 영상이에요. 후보를 다시 불러 주세요"
            )
        if body.focus_x is not None:
            hit = {**hit, "focus_x": body.focus_x}
        out = o.store.project_dir(pid) / "assets" / "video" / f"{scene_id}_pixabay_{body.id}"
        try:
            result = await source.fetch(hit, out)
        except (RuntimeError, MediaError) as e:
            raise HTTPException(502, f"동영상을 받지 못했어요: {e}") from e
        assets = [a.model_copy(deep=True) for a in p.assets or []]
        for a in assets:
            if a.scene_id == scene_id:
                a.image.path = result.path.relative_to(o.store.project_dir(pid)).as_posix()
                a.image.source, a.image.provider = result.source, result.provider
                a.image.credit = result.credit
        return await o.edit(pid, "assets", assets)

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
        o = orch(request)
        p = o.store.load(pid)
        base = o.store.project_dir(pid)
        cover = cover_path(p, base)
        return publish_kit(p, cover if cover and cover.exists() else None, cover_title(p, base))

    @app.post("/projects/{pid}/cover")
    async def make_cover(request: Request, pid: str, body: CoverIn | None = None) -> dict:
        """훅 장면 이미지에 문구를 얹은 커버(썸네일) 한 장. 같은 문구·이미지면 그대로 쓴다.

        body.title로 문구를 바꿀 수 있다("/"는 줄바꿈, 비우면 4단계 제목).
        """
        o = orch(request)
        p = o.store.load(pid)
        base = o.store.project_dir(pid)
        if body is not None and body.title is not None and p.strategy and p.timeline:
            save_cover_title(base, body.title)
        out = cover_path(p, base)
        if out is None or not p.timeline:
            raise HTTPException(409, "4단계 제목과 6단계 편집 지시서가 있어야 커버를 만들어요")
        if not out.exists():
            image = (base / p.timeline.scenes[0].image).resolve()
            if not image.is_relative_to(base.resolve()) or not image.exists():
                raise HTTPException(409, "첫 장면 이미지 파일이 없어요. 5단계를 다시 실행해 주세요")
            c = p.timeline.canvas
            try:
                await o.adapters.video.make_cover(image, cover_title(p, base), out, c.w, c.h, base)
            except MediaError as e:
                raise HTTPException(500, f"커버를 만들지 못했어요: {e}") from e
        return {"cover": out.relative_to(base).as_posix(), "cover_title": cover_title(p, base)}

    @app.post("/projects/{pid}/media", status_code=201)
    async def upload_media(
        request: Request,
        pid: str,
        files: Annotated[list[UploadFile], File()],
        attach: bool = True,
    ) -> dict:
        """사진·동영상 업로드. attach=True면 input.user_media에 추가(S5부터 재생성 필요).

        attach=False면 파일만 저장하고 경로를 돌려준다 — 장면 사진 교체(PATCH assets)용.
        동영상은 메모리에 다 올리지 않고 조각으로 나눠 저장한다(RAM 8GB PC).
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
            if ext not in UPLOAD_EXT | VIDEO_EXT:
                raise HTTPException(
                    415, f"지원하지 않는 형식: {f.filename} (jpg/png/webp, mp4/mov/webm)"
                )
            stem = re.sub(r"[^\w-]", "_", Path(f.filename or "photo").stem)[:40] or "photo"
            dest = media_dir / f"{stem}_{secrets.token_hex(3)}{ext}"
            if ext in VIDEO_EXT:
                await _save_video(f, dest)
            else:
                data = await f.read(MAX_UPLOAD_BYTES + 1)
                if len(data) > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"{f.filename}: 25MB를 넘는다")
                if not is_image(data):
                    raise HTTPException(
                        415, f"{f.filename}: 이미지 파일이 아니다 (내용이 JPEG/PNG/WEBP가 아님)"
                    )
                dest.write_bytes(data)
            saved.append(dest.relative_to(o.store.project_dir(pid)).as_posix())
        if not attach:
            return {"saved": saved, "user_media": p.input.user_media}
        inp = p.input.model_copy(update={"user_media": [*p.input.user_media, *saved]})
        p = await o.edit(pid, "input", inp)
        return {"saved": saved, "user_media": p.input.user_media}

    async def _save_video(f: UploadFile, dest: Path) -> None:
        first = await f.read(UPLOAD_CHUNK)
        if not is_video(first):
            raise HTTPException(
                415, f"{f.filename}: 동영상 파일이 아니다 (내용이 MP4/MOV/WEBM이 아님)"
            )
        size = len(first)
        try:
            with dest.open("wb") as out:
                out.write(first)
                while chunk := await f.read(UPLOAD_CHUNK):
                    size += len(chunk)
                    if size > MAX_VIDEO_BYTES:
                        raise HTTPException(413, f"{f.filename}: 300MB를 넘는다")
                    out.write(chunk)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise

    def _timeline_for_music(o: Orchestrator, pid: str) -> Timeline:
        p = o.store.load(pid)
        if p.timeline is None:
            raise HTTPException(409, "6단계(편집 지시서)를 먼저 만들어 주세요")
        if o.is_busy(pid):
            raise ProjectBusy(pid)
        return p.timeline.model_copy(deep=True)

    @app.post("/projects/{pid}/music")
    async def set_music(request: Request, pid: str, body: MusicIn) -> Project:
        """배경음악 분위기 바꾸기·다른 곡·끄기·음량. 바꾸면 7단계가 재생성 필요가 된다."""
        o = orch(request)
        tl = _timeline_for_music(o, pid)
        a = tl.audio
        if body.gain_db is not None:
            a.bgm_gain_db = body.gain_db
        if body.off:
            a.bgm, a.source, a.locked = None, None, True
        elif body.mood is not None or body.another:
            if body.mood is not None and body.mood not in MOOD_LABEL:
                raise HTTPException(400, f"모르는 분위기: {body.mood}")
            if body.mood is not None:
                a.mood = body.mood
            if body.another:
                a.variant += 1
            a.source, a.locked = "generated", True
            try:
                await ensure_bgm(o.adapters.video, o.store.project_dir(pid), tl)
            except MediaError as e:
                raise HTTPException(500, f"배경음악을 만들지 못했어요: {e}") from e
        elif body.auto:
            a.locked = False
        return await o.edit(pid, "timeline", tl)

    @app.post("/projects/{pid}/music/upload")
    async def upload_music(
        request: Request, pid: str, file: Annotated[UploadFile, File()]
    ) -> Project:
        """직접 가진 음악 파일(MP3/M4A/WAV)을 배경음악으로 쓴다.

        사용 권리는 업로드 체크리스트에서 확인한다.
        """
        o = orch(request)
        tl = _timeline_for_music(o, pid)
        ext = Path(file.filename or "").suffix.lower()
        if ext not in MUSIC_EXT:
            raise HTTPException(415, f"지원하지 않는 형식: {file.filename} (mp3/m4a/wav)")
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{file.filename}: 25MB를 넘는다")
        if not is_audio(data):
            raise HTTPException(
                415, f"{file.filename}: 음악 파일이 아니다 (내용이 MP3/M4A/WAV가 아님)"
            )
        media_dir = o.store.project_dir(pid) / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^\w-]", "_", Path(file.filename or "music").stem)[:40] or "music"
        dest = media_dir / f"{stem}_{secrets.token_hex(3)}{ext}"
        dest.write_bytes(data)
        a = tl.audio
        a.bgm = dest.relative_to(o.store.project_dir(pid)).as_posix()
        a.source, a.mood, a.locked = "user", None, True
        return await o.edit(pid, "timeline", tl)

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
