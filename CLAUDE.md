# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트

ShortForge — 사용자 입력(주제·타깃·톤)으로 YouTube 레퍼런스를 분석해 30초 숏폼(MP4 + SRT)을 만드는 7단계 파이프라인. 모든 단계는 **비용 ₩0**(무료 쿼터 + 로컬 오픈소스)으로만 구성한다.

문서 우선순위: `PRD.md`(무엇·왜, 충돌 시 최우선) > `PROJECT_PROMPT.md`(구현 지시서: 계약·스키마·API·DoD) > `PROJECT_PLAN.md`(Step별 실행 계획과 각 Step의 Gate·진행 상태) > `docs/DECISIONS.md`(확정된 결정 D1~D12, 근거 포함). Step을 끝내면 `PROJECT_PLAN.md`의 해당 Step에 상태와 측정값을 기록한다. 두 HTML 파일은 발표 자료와 UI 목업(번들 형식, 7탭 화면 설계 원본)이다.

## 명령어

배포(사용자): `shortforge/setup.bat`(최초 1회)과 `shortforge/start.bat`(API와 웹 UI를 127.0.0.1에 실행). 두 `.ps1` 파일은 PowerShell 5.1용이라 **UTF-8 BOM으로 저장해야 한다**(BOM이 없으면 cp949로 읽혀 한글이 깨진다). `start.bat`은 `frontend/.next`의 프로덕션 빌드를 띄우므로, 프론트를 고친 뒤에는 `npm run build`를 다시 해야 새 UI가 나온다(개발 서버와 `next build`는 같은 `.next`를 쓰므로 동시에 돌리지 않는다).

릴리스: GitHub **공개** 저장소 `awesome72/shortforge`(2026-10-21 공개 전환)에 사전 배포판으로 낸다(로컬 설치형, D1). 공개 저장소라 커밋에 키·`.env` 사본·`data/`가 들어가면 바로 노출된다: `.gitignore`가 `.env*`(`.env.example` 제외)를 막고, 커밋 전에 스테이징된 파일을 확인한다. 버전은 `backend/pyproject.toml`과 `backend/app/__init__.py`의 `__version__`을 함께 올리고(`tests/test_version.py`가 확인), `CHANGELOG.md`의 "다음 버전" 절을 옮긴 뒤 `git tag vX.Y.Z-beta.N` → `gh release create --prerelease`로 낸다. 내기 전에 새 clone에서 `setup.ps1`과 테스트를 돌려 본다.

백엔드 명령은 모두 `shortforge/backend`에서 `uv`로 실행한다 (Python 3.11, `.venv`는 uv가 관리).
웹 UI는 `shortforge/frontend`(Next.js 16, Tailwind v4)에서 실행한다.

```bash
DEV_FAKE_LLM=true uv run uvicorn app.main:app --port 8000 --reload   # API (키 없이 UI 개발 시 Fake LLM)
cd ../frontend && npm run dev                                         # http://localhost:3000
npx tsc --noEmit && npm run lint                                      # 프론트 검사 (새 clone은 먼저 npx next typegen)
```

```bash
uv sync                                   # 의존성 설치
uv run pytest -q                          # 전체 테스트
uv run pytest tests/test_orchestrator.py::test_rerun_marks_downstream_stale -q   # 단일 테스트
uv run ruff check . && uv run ruff format --check .
uv run python -m app.cli new "주제" --audience "타깃" --photos 사진폴더   # 프로젝트 ID 출력
uv run python -m app.cli run <id> [--from s4 | --step s2] [--fake-llm | --fake]
uv run python -m app.cli status|refs|show <id> · select <id> 1,3 · set-line <id> S2 "대사" · set-photo <id> S3 사진
                                          # M0 CLI. 편집 명령은 orch.edit()를 거쳐 뒤 단계를 stale로 만든다
uv run python ../scripts/render_spike.py [--images DIR] [--presets veryfast,medium] [--no-bgm]
                                          # 실제 S5→S7 경로 렌더 벤치마크 (LLM·YouTube만 Fake)
uv run python ../scripts/youtube_smoke.py [--keywords "a,b,c"] [--with-comments]
                                          # 실제 YouTube로 S2(+S3 댓글) 실행. 약 303 units, 같은 날 재실행은 0
uv run python ../scripts/llm_smoke.py [--inject]
                                          # 실제 LLM으로 S1→S4 + Gate 판정. --inject는 악성 댓글로 인젝션 방어 확인
uv run python ../scripts/image_smoke.py      # Cloudflare 1장 생성(약 156 Neurons) + Pixabay 1장, 크기·시간 확인
uv run python ../scripts/tts_blind_test.py   # 음성 후보·숫자 읽기 듣기 페이지 → data/blind_test/index.html
uv run python ../scripts/kpi_report.py      # data/metrics.jsonl → PRD §10 KPI 판정
python ../scripts/doctor.py [--offline] [--probe-llm]
                                          # 환경 점검(IMAGE_MODE의 Cloudflare 토큰·Pexels 키 포함). --probe-llm은 Gemini 1토큰 호출로 404·결제 연결(402)까지 확인
```

- 설정은 `shortforge/.env`(템플릿 `.env.example`)에서 `app/config.py`의 `Settings`로 읽는다. 엔진 전환은 `LLM_MODE`, `IMAGE_MODE`, `TTS_MODE`, `RENDER_PRESET` 등 설정값만으로 한다.
- FFmpeg는 winget으로 설치되어 PATH에 없을 수 있다. 코드는 `app/media.find_exe()`로 찾는다(PATH → `%LOCALAPPDATA%\Microsoft\WinGet\Links`).
- `test_render.py`는 실제 FFmpeg로 작은 캔버스(270×480)를 렌더하며, FFmpeg가 없으면 건너뛴다.
- 런타임 데이터는 `shortforge/data/`에 쌓이고 git에서 제외된다. `DATA_DIR`의 상대 경로는 실행 위치가 아니라 `shortforge/` 기준이다. 프로젝트 인덱스, 캐시, 쿼터 로그는 모두 `data/shortforge.db` 하나에 들어간다.
- 테스트는 YouTube·Cloudflare·Pexels·ComfyUI를 `httpx.MockTransport` 가짜 서버로 대체하므로 쿼터를 쓰지 않는다. `render_spike.py`도 YouTube를 Fake로 고정한다.
- `tests/conftest.py`의 autouse 픽스처가 모든 테스트에서 API 키를 더미로 덮어쓴다. 테스트가 개발자 `.env`의 실제 키에 기대면 새 clone에서만 깨진다(실제로 있었던 문제).
- API 서버는 `build_adapters(..., problems=[])`로 관대하게 조립한다. 키가 빠진 LLM·YouTube는 실행 시 `SetupRequired`를 내는 대체물이 되고, 이유는 `/config`의 `setup_problems`로 화면 배너에 뜬다. 키가 없는 이미지 소스는 체인에서 뺀다. CLI·스크립트는 지금처럼 바로 실패한다.
- 로그(`app/support.py`): API 서버는 `data/logs/app.log`(1MB×3 순환)에 `app.*`·`uvicorn.error` 로그를 남긴다. 단계 예외는 오케스트레이터가 traceback과 함께 남긴다. 로그와 `GET /support/bundle`(문제 보고 zip)은 설정의 키·토큰 값과 `key=` 쿼리를 `[숨김]`으로 지운다. 로그 메시지에 주제·대사를 넣지 않는다.
- 키 설정(`app/keys.py`): `GET /settings/keys`는 설정 여부만, `POST /settings/keys/check`는 무료 호출로 확인만, `POST /settings/keys`는 확인을 통과한 값만 `.env`의 해당 줄에 쓰고 실행 중인 `settings`에 바로 반영한 뒤 `app.state.rebuild`로 어댑터를 다시 만든다(실행 중인 프로젝트가 있으면 409). 결제가 연결된 Gemini 키(402)는 거절한다. 다른 사이트에서 localhost로 보내는 요청을 막으려고 Origin이 CORS 목록에 없거나 JSON이 아니면 거절한다. 테스트는 `create_app(env_path=...)`와 `app.state.key_transport`(MockTransport)를 쓴다.
- 고급 모드(D13, 선택·유료): `LLM_ADVANCED=anthropic|openai|openrouter`이면 `registry.build_llm()`이 기본 LLM을 `adapters/llm/routed.RoutedLLM`으로 감싼다. `ADVANCED_TASKS`(기본 `s3_factors,s4_strategy`)만 유료 어댑터로 보내고, 나머지는 무료 경로다. Anthropic은 `adapters/llm/advanced/anthropic_api.AnthropicAdapter`(공식 `anthropic` SDK 1.x, `httpx2` 기반), OpenAI·OpenRouter는 `advanced/openai_compat.OpenAICompatAdapter` 하나(httpx, Chat Completions, `response_format` json_schema `strict: false`, OpenRouter는 `provider.require_parameters`와 응답의 `usage.cost`)다. 고급 모드가 실패(키 오류·거절·연결)하거나 `app/spend.SpendMeter`의 하루 예산(UTC)을 넘으면 무료 경로로 처리하고 단계 경고를 남긴다. 키가 없거나 가격표(`spend.PRICES`)에 없는 모델이면 고급 모드만 빠지고 `setup_problems`에 이유가 뜬다. 요청은 `output_config.format`(json_schema, `strict_schema()`로 미지원 제약 제거)과 `effort`를 쓰고, 지원 모델은 `fallbacks: "default"`(server-side-fallback-2026-07-01)를 켠다. 썸네일은 URL로 넘긴다. 비용은 응답 토큰 × 가격표로 `spend_log`와 `llm_call`(`usd`)에 남는다. 켜기·끄기는 `POST /settings/advanced`(과금 동의와 그 제공자의 키 필요, 끌 때는 스위치만 내림). 키 확인은 모두 토큰을 쓰지 않는 조회다(Anthropic·OpenAI 모델 목록, OpenRouter `/key`). 모델·가격을 바꾸면 `spend.PRICES`만 고친다(가격표에 없는 모델은 쓰지 않는다). 실측 결과는 DECISIONS D13 근거에 있다. 테스트는 Anthropic에 `httpx2.MockTransport`를 `http_client`(앱에서는 `app.state.anthropic_http_client`)로, OpenAI·OpenRouter에 `httpx.MockTransport`(앱에서는 `app.state.key_transport`)를 넣는다.
- `DELETE /projects/{id}`는 폴더와 목록 행을 지운다(변형은 남음). `POST /projects/{id}/cleanup`은 현재 본문과 **모든 버전**이 가리키지 않는 assets/·media/ 파일만 지운다. 음성의 `*.words.json`은 렌더가 이름으로 찾으므로 음성 경로에 딸린 것으로 보고 남긴다.
- CI: `.github/workflows/ci.yml`(windows-latest)이 push·PR마다 `uv sync --locked`, ruff, pytest, `npm ci`, tsc, lint, build를 돌린다. FFmpeg가 없어 `test_render.py`는 건너뛴다. `.gitattributes`가 `.bat`·`.ps1`을 CRLF로 꺼낸다.
- CLI는 `run`일 때만 실제 어댑터를 만든다. 편집 명령(`select`·`set-line`·`set-photo` 등)은 Fake 어댑터를 써서 키 없이 동작한다.

## 아키텍처

### Project JSON이 유일한 단계 간 통로
`app/schemas/project.py`의 `Project`가 단일 진실 원천이다. 각 단계는 **선언한 키만 읽고 출력 키 하나만 쓴다**. 단계끼리 직접 import하거나 호출하지 않는다.

| 단계 | 읽기 | 쓰기 |
|---|---|---|
| s1 입력 | (자기 출력 `input`을 `ctx.current()`로) | `input` |
| s2 탐색 | `input` | `refs` |
| s3 요인 | `input`, `refs` | `factors` |
| s4 전략 | `input`, `factors`, `refs`(제목 유사도 검사) | `strategy` |
| s5 자산 | `input`(user_media), `strategy` | `assets` |
| s6 타임라인 | `strategy`, `assets` | `timeline` |
| s7 렌더 | `timeline` | `render` |

이 표의 기준 구현은 `app/orchestrator.py`의 `_build_pipeline()`이다. 단계 함수는 `async def run(ctx: StepContext) -> <출력>` 형태이고, 반환값을 오케스트레이터가 스키마로 검증해 기록한다. `ctx.read(key)`는 선언하지 않은 키를 읽으면 `ContractViolation`을 낸다. `ctx.warn()`의 내용은 `project.warnings[step]`에 남고, `StepInputError` 메시지는 사용자에게 그대로 보인다.

### 오케스트레이터 규칙 (`app/orchestrator.py`)
- 상태: `idle | running | done | stale | error`. 단계는 읽는 키를 쓰는 앞 단계가 모두 `done`일 때만 실행할 수 있다(아니면 `StepBlocked`).
- 내용 조건(`app/readiness.py`): 앞 단계가 done이어도 내용이 모자라면(지금은 S6: 장면 이미지·음성이 빈 경우) `orch.not_ready()`가 이유를 돌려준다. 실행 API는 그 이유로 409(`StepBlocked`)를 내고, `run_all`은 실패시키지 않고 그 앞에서 멈춘다. 이유 문구는 `image_hint()`가 지금 이미지 방식과 가진 키에 맞춰 고른다(예: upload인데 Cloudflare 키가 있으면 'AI 생성'으로 바꾸라고 안내). `GET /projects/{id}`의 `not_ready`, `/config`의 `image_unused`(키는 있는데 이미지 방식에 없는 소스)로 화면에 보인다. 실제로 이미지 방식이 upload로 돌아간 상태에서 사용자가 S6을 6번 눌러 같은 오류를 본 일이 계기다.
- 단계별 LLM 처리 기록: 오케스트레이터가 단계마다 모은 `llm_call`을 요약해 `project.llm_usage[step]`(모델·제공자·호출 수·고급 모드 비용)에 남긴다. 화면은 단계 버튼 옆에 "처리: 모델 · 고급 모드 $…"로 보여 준다.
- **Stale 전파:** 단계 출력이 바뀌면(실행 성공이든 `edit()`를 통한 사용자 편집이든) 뒤 단계는 출력이 있으면 `stale`, 없으면 `idle`이 된다. 자동 재실행은 하지 않는다.
- 단계 예외는 `status=error` + `errors[step]`로 기록하고 이전 출력은 보존한다. `run_all`은 첫 오류에서 멈춘다.
- 프로젝트별 `asyncio.Lock`으로 동시 실행·편집을 막는다(`ProjectBusy`). 진행 이벤트는 `EventBus`로 발행된다(SSE용).
- 저장(`app/store.py`): `data/projects/{id}/project.json`을 임시 파일 교체로 원자적 저장하고, 버전은 `versions/v{n}.json`, 목록은 SQLite에 둔다. `running` 같은 일시 상태는 `snapshot=False`로 저장한다. Windows에서는 백신·인덱서 잠금 때문에 교체가 `PermissionError`를 낼 수 있어 재시도 로직이 있다. 이 로직을 제거하면 테스트가 간헐적으로 깨진다.

### API·웹 UI (`app/main.py`, `frontend/`)
- 실행 엔드포인트는 `orch.start_run_*()`로 백그라운드 태스크를 띄우고 202를 돌려준다. 진행은 `GET /projects/{id}/events`(SSE)로 받는다. **실행 엔드포인트는 반드시 `async def`여야 한다.** 동기 함수는 스레드풀에서 돌아 이벤트 루프에 태스크를 만들 수 없다.
- 필드 단위 전파(`orchestrator.FIELD_FIRST_READER`): `input.user_media`만 바뀌면 S5부터 stale이 된다. 장면 사진 교체는 `POST /media?attach=false` 뒤 `PATCH assets`로 하며, S6부터 stale이 된다.
- 프로젝트 ID는 `ProjectStore.project_dir()`에서 `prj_[0-9a-f]{12}` 형식을 강제한다. 이 검사가 없으면 `pid=..`로 data/ 폴더 전체가 노출된다(보안 수정 `050baec`). `GET /files/{path}`는 프로젝트 폴더 밖 경로를 404로 막는다. 업로드는 확장자와 함께 파일 시그니처도 검사한다. 웹 UI와 API는 출처가 달라 `<a download>`가 무시되므로 `?download=1`(첨부 응답)을 쓴다.
- 6단계 미리보기(`components/TimelinePreview.tsx`)는 렌더 없이 timeline의 이미지·음성을 브라우저에서 이어 재생한다. 모션은 Web Animations로 FFmpeg zoompan 방향을 흉내 내고, BGM과 어절 자막은 없다.
- 프론트 `lib/types.ts`는 백엔드 스키마와 같은 모양이다. 계약이 바뀌면 함께 바꾼다. `lib/useProject.ts`는 SSE 이벤트가 오면 Project를 다시 읽는다(120ms로 묶어서).
- Next 16 주의: 버전에 맞는 문서는 `frontend/node_modules/next/dist/docs/`에 있다(`frontend/AGENTS.md`). 동적 `params`는 Promise이고 Suspense 안에서 읽어야 한다. Tailwind v4에서 전역 CSS는 `@layer base` 안에 두어야 유틸리티 클래스가 이긴다.

### A/B 변형·버전 (F-W6, F-W5)
- `orch.duplicate_project()`는 S1~S4 출력·상태만 복사하고 S5~S7은 idle로 둔다(변형은 대사·제목을 바꿔 S5부터 다시 만드는 용도). `media/`는 `store.copy_media()`로 복사한다. 변형 문자는 같은 원본의 기존 변형 수로 정한다(B, C…).
- `orch.restore_version()`은 스냅샷을 새 버전으로 저장한다. S5~S7은 파일이 그 뒤에 덮어써졌을 수 있어 done이면 stale로 바꾼다.
- `ProjectRow`에 열을 추가하면 `store._ROW_MIGRATIONS`에도 넣는다. SQLModel `create_all`은 기존 테이블을 바꾸지 않는다.

### 후보 고르기·업로드 체크리스트 (F-5.4, AI 고지)
- `POST /projects/{id}/scenes/{scene}/candidates?n=3`은 seed+1..+n 후보를 `assets/candidates/`에 만들기만 하고 적용하지 않는다. `POST .../image/select`는 그 폴더 안의 실제 파일만 받으며(경로 조작은 400), prompt·negative·query는 기존 값을 유지한 채 `edit()`로 assets를 바꿔 S6부터 stale로 만든다.
- `app/publish.publish_kit()`(`GET /projects/{id}/publish`)은 실제로 쓴 자산(합성 음성·AI 이미지·무료 사진·본인 사진)을 보고 체크리스트와 설명란 문구를 만든다. 플랫폼 정책을 단정하지 않고 업로드 화면에서 확인하라고 안내한다. 체크 상태는 브라우저 localStorage에만 둔다.

### KPI (`app/metrics.py`, `app/kpi.py`)
- 오케스트레이터가 `project_created`, `step_done`/`step_error`(초, S2·S3 units, S3 근거 수), `edited`, `render_done`, `project_duplicated`, `version_restored` 이벤트를 남기고, API는 `download`를 남긴다. Gemini 어댑터는 요청마다 `llm_call`(작업·모델·요청 초·재시도 대기 초·사고 토큰)을 `app.metrics.record_llm_call()`로 남기고, 오케스트레이터가 단계마다 `LLM_CALLS`(ContextVar)에 모아 단계 이름과 함께 기록한다(실패한 단계 포함). `kpi_report.py`가 작업·모델별 속도 표를 보여 준다. 기록 위치는 `data/metrics.jsonl`이며 주제·대사는 넣지 않는다. 프로젝트는 `orch.create_project()`로 만들어야 생성 이벤트가 남는다.

### 어댑터 (`app/adapters/`)
모든 외부 모델·API는 `base.py`의 추상 클래스(`LLMAdapter`, `YouTubeAdapter`, `TTSAdapter`, `ImageAdapter`, `VideoAdapter`) 뒤에 둔다. 조립은 `registry.build_adapters()`가 맡는다.
- `fake.py`: 결정론적 Fake. 테스트와 오프라인 개발에 쓴다. `FakeLLM`은 `task` 이름(`s1_keywords`, `s2_relevance`, `s3_thumbnails`, `s3_factors`, `s4_strategy`, `s4_shorten`, `s5_image_prompts`, `s6_timeline`)별 `_<task>` 메서드로 응답한다. LLM 호출을 추가하면 여기에도 응답을 추가해야 한다. `FakeTTS`는 rate를 반영해 길이를 바꾼다(길이 보정 테스트용).
- 실제 구현: `llm/gemini.py`, `llm/ollama.py`, `youtube/api.py`, `tts/edge.py`(mp3 + `*.words.json` 어절 타이밍), `video/ffmpeg.py`, `image/{upload,cloudflare,pixabay,pexels,comfyui,chain}.py`. `build_adapters(settings, fake_llm=True)`는 LLM만 Fake로 둔다(측정 스크립트용).
- 어댑터가 `notices`/`drain_notices()`를 가지면(Gemini, ImageChain), 오케스트레이터가 단계가 끝날 때 그 알림을 단계 경고로 옮긴다. 무료 한도 소진으로 모델이나 이미지 소스가 바뀐 사실을 사용자에게 알리는 통로다.
- LLM 어댑터는 `llm/common.JSONLLMAdapter`를 상속하고 `_complete()`만 구현한다. 스키마 변환(`llm_schema`: $ref 펼치기), 코드 펜스 제거, 검증 실패 시 오류를 넣은 2회 재시도는 공통 처리다.
- Gemini 무료 등급 일일 한도는 모델마다 따로다(3.8-flash는 하루 20회). `GeminiAdapter.model_for(task)`가 S1·S2 관련성·S3 썸네일 관찰·S4 대사 줄이기·S5 영문 프롬프트·S6를 `GEMINI_MODEL_LIGHT`로 보낸다. 일일 한도 429(`PerDay`)는 기다리지 않고 경량 모델로 넘긴다. 503 과부하는 경량 모델로 넘길 수 있으면 3초 한 번만 기다리고 넘기며(`SERVER_WAITS_BEFORE_FALLBACK`), 넘길 모델이 없을 때만 5·15·30초를 기다린다. 과부하가 난 모델은 10분간 건너뛴다(`OVERLOAD_COOLDOWN_SEC`). 주 모델 요청에만 `GEMINI_THINKING_LEVEL`(기본 `low`)을 넣는다. 경량 모델에는 넣지 않는다. low로 바꾼 근거와 Gate 결과는 `config.py` 주석에 있고, 바꾸면 `llm_smoke.py --thinking <값> [--inject]`로 Gate와 요청 시간을 다시 확인한다. 같은 알림은 한 번만 남긴다. `notices`에 남긴 알림은 오케스트레이터가 단계 경고로 옮긴다(D11).
- Gemini: 모델은 버전 고정 이름을 쓴다(D7). `gemini-2.5-flash`는 신규 사용자에게 404를 낸다. 결제가 연결된 프로젝트의 키는 유료 등급이라 쓰지 않는다. 모델 목록에 있다고 호출 가능한 것은 아니므로 `doctor.py --probe-llm`으로 확인한다.
- 이미지(D12): 어댑터는 `ImageRequest`(영문 prompt·seed·검색어 query)를 받아 `ImageResult`(경로·source·provider·credit) 또는 None을 돌려준다. `IMAGE_MODE`에 생성·검색 소스가 하나라도 있으면 `registry.build_image()`가 `image/chain.ImageChain`으로 감싼다. 체인은 `ImageQuotaExceeded`·오류·결과 없음이면 다음 소스로 넘어가고 `notices`를 남긴다. `image/cloudflare.py`: FLUX.2 klein은 **multipart만** 받는다(JSON이면 거부). schnell은 `prompt`·`steps`만 받아 크기·seed를 지정할 수 없다. Neurons는 가격표로 추정해 `neuron_log`(UTC 날짜)에 센다. `stock` 토큰은 `image/pixabay.py`를 가리킨다. Pexels는 2026-10 신규 키 발급이 중단돼 `pexels`로 명시할 때만 쓴다. Pixabay 약관상 검색은 `app/cache`로 24시간 캐시하고, 이미지는 hotlink하지 않고 내려받으며, credit을 남긴다. 사진 어댑터들은 세로 사진을 검색하고 같은 실행에서 쓴 사진은 피한다. S5의 `fetch_image()`는 API의 장면 이미지 다시 만들기(`POST /projects/{id}/scenes/{scene}/image`, seed+1)도 쓴다. S5를 다시 실행하면 `ImageAsset.basis`(장면 묘사+스타일 시드)가 같은 장면은 이전 이미지를 그대로 쓴다(`reusable_images`). 생성 파일 이름은 `image_stem()`(장면·seed·내용 해시)으로 정해, 장면 번호가 바뀌어도 재사용 중인 파일을 덮어쓰지 않는다.
- 이미지 프롬프트(`app/image_prompt.py`, `prompts/s5_image_prompts.md`): 최종 프롬프트는 `build_prompt(장면 영문 묘사, LLM이 옮긴 영문 style, QUALITY)`이고, `clean_image_prompt()`가 글자를 부르는 말(자막·제목·로고·포스터·간판·따옴표 문구), 화면비·레이아웃 말(9:16·숏폼), 부정문 조각(no·without)을 뺀다. `fetch_image()`도 요청 직전에 한 번 더 거른다(예전 프로젝트의 다시 만들기 대비). 계기: S4 style_seed의 '굵은 흰색 자막'을 그대로 붙였더니 FLUX가 장면마다 큰 영문 문구를 그렸다(2026-10-21). FLUX에는 negative 입력이 없고 부정문은 그 대상을 오히려 그린다. S5 LLM은 `style`과 주인공 고정 묘사 `subject`(audience·region에 맞는 인물, 성별·나이·머리·옷)를 함께 만들고, 사람이 나오는 장면에 subject를 그대로 넣어 장면마다 다른 사람이 나오지 않게 한다. 프롬프트 규칙을 바꾸면 `PROMPT_REV`를 올린다: `ImageAsset.rev`가 낮은 **생성** 이미지는 S5 재실행 때 재사용하지 않는다(사진·사용자 이미지는 그대로). Cloudflare 기본 크기는 864×1536(720×1280과 같은 6타일 = 156 Neurons). klein 9B·FLUX.2 dev는 장당 약 1,364·4,500 Neurons라 무료 한도로 쓰지 않는다.
- `image/comfyui.py`는 원격 GPU 장비의 ComfyUI API(`/prompt` → `/history` → `/view`)를 쓴다. 워크플로는 `{{자리표시자}}`가 있는 API 형식 JSON이며, 값 전체가 자리표시자면 숫자 타입을 그대로 유지한다. 개발 PC에는 GPU가 없어 `tests/test_comfyui.py`의 가짜 서버로만 검증했다.
- YouTube 어댑터의 모든 호출은 캐시 → `QuotaMeter.check` → 요청 → `record` 순서다. 쿼터 날짜는 PT 기준(`app/quota.pt_today`)이다. 네트워크 오류는 쿼터를 기록하지 않고, 서버 응답(오류 포함)은 기록한다.

### 렌더 파이프라인 (`app/adapters/video/ffmpeg.py`, `app/subtitles.py`)
- 장면 k의 시작 시각은 `S_k = Σ d_j`(j<k, `d` = 음성 + pad)이다. 전환 길이 `T_k`만큼 클립 k를 앞으로 늘리고, xfade offset은 `S_k − T_k`, 음성은 `adelay`로 정확히 `S_k`에 놓는다. 총 길이는 `Σd`이다. 타이밍을 고칠 때는 이 불변식을 유지한다.
- FFmpeg/ffprobe는 `app/media.run()`으로만 실행한다. asyncio 서브프로세스가 아니라 스레드 기반 subprocess다. Windows `uvicorn --reload`의 SelectorEventLoop가 asyncio 서브프로세스를 지원하지 않기 때문이며, `tests/test_media_loop.py`가 이를 지킨다.
- 장면 클립은 병렬(`workers` = 코어 수의 절반)로 zoompan 인코딩한다. 클립 이름은 입력(이미지 파일 크기·수정 시각, 필터, 인코딩 설정, `CLIP_VERSION`)의 해시라서 같은 클립이 있으면 다시 만들지 않고, 쓰지 않게 된 클립은 렌더 끝에 지운다. 클립을 만드는 방식을 바꾸면 `CLIP_VERSION`을 올린다. `clip_preset`을 ultrafast로 두면 클립은 빨라지지만 최종 SSIM이 0.987로 떨어져 기본값은 최종 preset과 같다. 합성은 filter_complex 하나로 처리한다(`render/work/graph.txt`에 저장됨). ffmpeg는 `cwd=project_dir`로 실행해서 `ass=` 필터에 상대 경로를 쓴다(Windows 경로 이스케이프를 피하기 위함).
- 자막은 Whisper가 아니라 TTS 어절 타이밍으로 만든다. Edge-TTS 7.x는 `boundary="WordBoundary"`를 명시해야 한다. 타이밍에 문장부호가 없으므로 원문 대사(`caption.text`)에서 쉼표·마침표 위치를 찾아 끊는다. 침묵 구간은 강제 구분으로, 그 너머로 자막을 합치지 않는다.

### LLM 프롬프트
`app/prompts/sN_*.md`의 첫 줄은 반드시 `version: x.y`여야 한다(`app/llm.load_prompt`가 검사함). 레퍼런스 제목·댓글 같은 외부 텍스트는 `wrap_untrusted()`로 감싼다. S3는 선택된 영상을 가리키지 않는 evidence를 지우고, 근거가 없어진 요인은 버린다. `hook`/`visual` 요인은 항상 `estimated`로 둔다. 근거 필드 허용 목록(`s3_factors.EVIDENCE_FIELDS`)은 S3 프롬프트에 실제로 넣는 필드와 같아야 한다. 둘은 함께 바꾼다.
- 썸네일 비전 분석(F-3.3): `LLMAdapter.supports_images`가 참이면 S3가 먼저 `s3_thumbnails`(경량 모델, 1회, 최대 8장)로 썸네일을 관찰하고 `thumbnail` 필드로 블록에 넣는다. 썸네일은 **내려받지 않고** URL을 `generate_json(..., images=[url])`로 넘겨 Gemini가 직접 읽는다(`types.Part.from_uri`). 관찰 결과도 이미지 속 외부 텍스트라 `wrap_untrusted()`로 감싼다. 실패하면 경고만 남긴다. Ollama 어댑터는 이미지를 받지 않는다.
- S5는 `tts_script()`로 대사를 정리하되 숫자는 바꾸지 않는다(자막이 TTS 어절에서 나오므로). 음성은 이미지 쪽(영문 프롬프트 → 이미지)과 `TaskGroup`으로 동시에 만들고(서로 의존하지 않는다), 동시에 3개씩 합성하며, 합계가 목표 ±15%를 벗어나면 `fit_rate()`로 rate를 정해 한 번 다시 합성한다(−20%~+25%). 최종 오디오는 `loudnorm`으로 −14 LUFS에 맞춘다. S6는 규칙 기반 타임라인이 경로·길이를 정하고, LLM(`s6_timeline`)은 모션·전환·자막 스타일만 덮어쓴다. 첫 장면 전환은 항상 cut이다.
- S1 키워드는 2~3단어의 넓은 검색어여야 한다. "…후기", "…변화"처럼 좁은 키워드는 최근 90일 숏폼 검색 결과가 0개가 되기 쉽다. S2는 관련 후보가 하나도 없으면 점수 순으로라도 고르고, 레퍼런스가 4개 미만이면 경고한다.
- S4는 대사 분량을 약 6자/초(Edge-TTS 실측)로 검사해 너무 길면 줄이게 한다. S5의 속도 보정은 그다음 안전망이다.
- S2는 점수 상위 20개 후보를 LLM(`s2_relevance`)으로 관련성 판정한다. 실패해도 S2를 실패시키지 않는다. S4는 `review()`로 (치명/교정/참고) 문제를 나누고, 치명·교정 문제는 `[수정 요청]`을 붙여 최대 3회 재생성한다. 교정 문제가 대사 길이뿐이면 재생성하기 전에 `shorten_lines()`가 긴 대사만 경량 모델(`s4_shorten`)로 줄인다(주 모델은 재생성 때 글자 수를 잘 못 맞춘다). 길이 교정 요청에는 지금 대사를 함께 적는다. 사용자 입력에는 쓸 수 있는 factor 이름 목록을 넣는다. 프롬프트를 바꾸면 첫 줄 `version:`을 올린다.

## 절대 제약 (`PROJECT_PROMPT.md` §2, §12)
- 기본 경로에서는 과금 API·SDK(OpenAI, Anthropic, ElevenLabs, Replicate, Runway, Vertex 등)를 쓰지 않는다. 예외는 D13의 선택형 고급 모드뿐이다: 유료 LLM SDK는 `app/adapters/llm/advanced/` 안에서만 import하고, registry가 `LLM_ADVANCED`가 켜졌을 때만 지연 import한다. `tests/test_cost_guard.py`가 (1) 그 폴더 밖의 유료 SDK import, (2) 기본 설정으로 서버를 띄웠을 때 유료 SDK 모듈 로드, (3) 기본 설정의 유료 어댑터 생성, (4) `pyproject.toml` 의존성 허용 목록을 검사한다. 새 의존성은 허용 목록에 추가하고 이유를 남긴다.
- YouTube: `search.list`(100 units) 전에 캐시를 확인한다. 통계는 `videos.list`/`channels.list`로 50개씩 일괄 조회한다. S2 1회는 400 units 이하여야 하므로 검색은 키워드 상위 3개까지만 한다(`s2_search.MAX_SEARCH_KEYWORDS`). 일 8,000 units를 넘으면 차단한다. API 키를 여러 개 돌려 쓰는 로직은 금지다.
- 무료 등급만 쓴다. 매일 다시 채워지는 무료 한도(Gemini, Cloudflare, Pixabay)는 괜찮지만, 체험판·소액 크레딧(Hugging Face 등)에 기대는 경로는 만들지 않는다. 결제가 연결된 Gemini 키는 유료 등급이다(`doctor.py --probe-llm`이 402로 감지한다).
- 레퍼런스 영상·이미지·음성은 다운로드하지 않는다(yt-dlp 금지). 메타데이터, 통계, 공개 댓글, 썸네일 URL만 쓴다.

## 개발 환경 메모
개발 PC는 GPU가 없고(Intel UHD 620) RAM이 8GB이며 CPU는 i5-8265U다. 그래서 기본 경로는 "업로드 사진 + Edge-TTS + Gemini 무료 등급"이다(D3, D4). ComfyUI/FLUX/Wan을 로컬에서 실행하는 것은 전제하지 않는다. 문서와 사용자 커뮤니케이션은 한국어로 한다.
