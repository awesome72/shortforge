# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트

ShortForge — 사용자 입력(주제·타깃·톤)으로 YouTube 레퍼런스를 분석해 30초 숏폼(MP4 + SRT)을 만드는 7단계 파이프라인. 모든 단계는 **비용 ₩0**(무료 쿼터 + 로컬 오픈소스)으로만 구성한다. 백엔드 `shortforge/backend`(Python 3.11, FastAPI, Pydantic v2, SQLite), 웹 UI `shortforge/frontend`(Next.js 16, Tailwind v4).

문서 우선순위: `PRD.md`(무엇·왜, 충돌 시 최우선) > `PROJECT_PROMPT.md`(구현 지시서: 계약·스키마·API·DoD) > `PROJECT_PLAN.md`(Step별 실행 계획과 Gate·진행 상태) > `docs/DECISIONS.md`(확정된 결정 D1~D23, 근거 포함). **기능별 동작·숫자·경위는 `docs/ARCHITECTURE.md`**에 있다(이 파일은 요약). Step을 끝내면 `PROJECT_PLAN.md`의 해당 Step에 상태와 측정값을 기록한다. 루트의 HTML 파일은 발표 자료와 UI 목업이다.

## 명령어

배포(사용자): `shortforge/setup.bat`(최초 1회)과 `shortforge/start.bat`(API와 웹 UI를 127.0.0.1에 실행). 두 `.ps1` 파일은 PowerShell 5.1용이라 **UTF-8 BOM으로 저장해야 한다**(BOM이 없으면 cp949로 읽혀 한글이 깨진다). `start.bat`은 `frontend/.next`의 프로덕션 빌드를 띄우므로, 프론트를 고친 뒤에는 `npm run build`를 다시 해야 새 UI가 나온다(개발 서버와 `next build`는 같은 `.next`를 쓰므로 동시에 돌리지 않는다).

릴리스: GitHub **공개** 저장소 `awesome72/shortforge`에 사전 배포판으로 낸다(로컬 설치형, D1). 공개 저장소라 커밋에 키·`.env` 사본·`data/`가 들어가면 바로 노출된다: `.gitignore`가 `.env*`(`.env.example` 제외)를 막고, 커밋 전에 스테이징된 파일을 확인한다. 버전은 `backend/pyproject.toml`과 `backend/app/__init__.py`의 `__version__`을 함께 올리고(`tests/test_version.py`가 확인), `CHANGELOG.md`의 "다음 버전" 절을 옮긴 뒤 `git tag vX.Y.Z-beta.N` → `gh release create --prerelease`로 낸다. 내기 전에 새 clone에서 `setup.ps1`과 테스트를 돌려 본다.

백엔드 명령은 모두 `shortforge/backend`에서 `uv`로 실행한다(`.venv`는 uv가 관리). 웹 UI 명령은 `shortforge/frontend`에서 실행한다.

```bash
DEV_FAKE_LLM=true uv run uvicorn app.main:app --port 8000 --reload   # API (키 없이 UI 개발 시 Fake LLM)
cd ../frontend && npm run dev                                         # http://localhost:3000
# start.bat(프로덕션 .next)을 띄운 채로 개발할 때: NEXT_DIST_DIR=.next-dev NEXT_PUBLIC_API_BASE=http://127.0.0.1:8001 npx next dev -p 3001
#   (API도 다른 포트로: CORS_ORIGINS='["http://localhost:3001"]' uv run uvicorn app.main:app --port 8001, DATA_DIR도 따로)
npx tsc --noEmit && npm run lint                                      # 프론트 검사 (새 clone은 먼저 npx next typegen)
npm run build && npm run e2e                                          # 화면 자동 테스트 (Playwright + Edge, Fake API를 8000에 띄움)
# start.bat이 3000·8000을 쓰고 있으면: NEXT_DIST_DIR=.next-e2e NEXT_PUBLIC_API_BASE=http://127.0.0.1:8010 npx next build
#   → E2E_API_PORT=8010 E2E_WEB_PORT=3010 NEXT_DIST_DIR=.next-e2e npx playwright test
```

```bash
uv sync                                   # 의존성 설치
uv run pytest -q                          # 전체 테스트
uv run pytest tests/test_orchestrator.py::test_rerun_marks_downstream_stale -q   # 단일 테스트
uv run ruff check . && uv run ruff format --check .
uv run python -m app.cli new "주제" --audience "타깃" --photos 사진폴더   # 프로젝트 ID 출력
uv run python -m app.cli run <id> [--from s4 | --step s2] [--fake-llm | --fake]
uv run python -m app.cli status|refs|show <id> · select <id> 1,3 · set-line <id> S2 "대사" · set-photo <id> S3 사진
                                          # M0 CLI. 실제 어댑터는 run만 만든다. 편집 명령은 Fake 어댑터로 orch.edit()를 거쳐 뒤 단계를 stale로 만든다
uv run python ../scripts/render_spike.py [--images DIR] [--presets veryfast,medium] [--no-bgm]
                                          # 실제 S5→S7 경로 렌더 벤치마크 (LLM·YouTube만 Fake)
uv run python ../scripts/youtube_smoke.py [--keywords "a,b,c"] [--with-comments]
                                          # 실제 YouTube로 S2(+S3 댓글) 실행. 약 410 units, 같은 날 재실행은 0
uv run python ../scripts/llm_smoke.py [--inject] [--thinking <값>]
                                          # 실제 LLM으로 S1→S4 + Gate 판정. --inject는 악성 댓글로 인젝션 방어 확인
uv run python ../scripts/videogen_smoke.py 그림.png --space   # 실제 공개 Space로 영상 1개 (D20, 호출당 요금 없음, 그림이 외부로 올라간다)
uv run python ../scripts/videogen_smoke.py 그림.png [--yes]   # 실제 Hugging Face 유료 경로로 영상 1개 (D19, 비용 약 $0.07, --yes 없으면 값만 표시)
uv run python ../scripts/image_smoke.py      # Cloudflare 1장 생성(약 156 Neurons) + Pixabay 1장, 크기·시간 확인
uv run python ../scripts/tts_blind_test.py   # 음성 후보·숫자 읽기 듣기 페이지 → data/blind_test/index.html
uv run python ../scripts/kpi_report.py      # data/metrics.jsonl → PRD §10 KPI 판정
uv run python ../scripts/make_samples.py     # 다듬기 화면 견본(public/samples/) 다시 만들기: 그림 방식·목소리를 바꾸면
python ../scripts/doctor.py [--offline] [--probe-llm]
                                          # 환경 점검. --probe-llm은 Gemini 1토큰 호출로 404·결제 연결(402)까지 확인
```

- 설정은 `shortforge/.env`(템플릿 `.env.example`)에서 `app/config.py`의 `Settings`로 읽는다. 엔진 전환은 `LLM_MODE`, `IMAGE_MODE`, `TTS_MODE`, `RENDER_PRESET` 등 설정값만으로 한다. 런타임 데이터는 `shortforge/data/`(git 제외, `DATA_DIR` 상대 경로는 `shortforge/` 기준)이고 프로젝트 인덱스·캐시·쿼터 로그는 `data/shortforge.db` 하나다.
- 테스트는 외부 서비스를 `httpx.MockTransport` 가짜 서버로 대체해 쿼터를 쓰지 않는다. `tests/conftest.py`의 autouse 픽스처가 API 키를 더미로 덮어쓴다(개발자 `.env`의 실제 키에 기대면 새 clone에서만 깨진다). `test_render.py`는 실제 FFmpeg로 작은 캔버스를 렌더하고 FFmpeg가 없으면 건너뛴다.
- CI(`.github/workflows/ci.yml`, windows-latest): ruff, pytest(FFmpeg 설치, `-rs`), `npm ci`, tsc, lint, build, e2e. e2e 8개는 `DEV_FAKE_ALL=true`(모든 어댑터 Fake) API와 `next start`를 띄우고 브라우저는 `channel: msedge`다. Fake 어댑터는 실패하지 않으므로 실패·유료 화면은 `page.route`로 응답을 바꿔 확인한다.

## 함정 (어기면 실제로 깨졌던 것)

- **`tsconfig.json`:** `.next-dev`·`.next-e2e` 빌드는 Next가 `tsconfig.json`에 경로를 추가한다. 커밋 전에 `git checkout -- shortforge/frontend/tsconfig.json`.
- **`globals.css`를 고친 뒤에는 `.next*` 빌드 폴더를 지우고 빌드한다:** turbopack 캐시가 예전 CSS를 써서 바뀐 토큰이 빠진 빌드가 나왔다.
- **같은 `data/`에 서버 두 개 금지:** API 시작 때 `recover_interrupted()`가 다른 서버에서 실행 중인 단계를 error로 바꾼다. 개발 서버는 다른 `DATA_DIR`로.
- **실행 엔드포인트는 `async def`:** 동기 함수는 스레드풀에서 돌아 이벤트 루프에 태스크를 만들 수 없다.
- **FFmpeg/ffprobe는 `app/media.run()`으로만:** 스레드 기반 subprocess다(Windows `--reload`의 SelectorEventLoop는 asyncio 서브프로세스를 지원하지 않는다, `test_media_loop.py`). 실행 파일은 `media.find_exe()`로 찾는다(winget 설치는 PATH에 없을 수 있다).
- **BaseHTTPMiddleware 금지:** SSE를 감싼다. 미들웨어는 ASGI로(`app/guard.py`).
- **버전 값을 올려야 캐시·재사용이 맞는다:** 프롬프트 파일 첫 줄 `version:`(`load_prompt`가 검사), 이미지 프롬프트 규칙 → `image_prompt.PROMPT_REV`, 장면 클립 만드는 방식 → `CLIP_VERSION`, 렌더 결과가 눈에 띄게 달라지면 `s7_render.RENDER_QUALITY`, 음악 합성 → `MUSIC_VERSION`, 커버 → `COVER_VERSION`.
- **함께 고쳐야 하는 짝:** `ProjectRow` 열 ↔ `store._ROW_MIGRATIONS`(`create_all`은 기존 테이블을 바꾸지 않는다) · LLM 호출 추가 ↔ `fake.FakeLLM._<task>` · 백엔드 스키마 ↔ 프론트 `lib/types.ts` · 실패 종류 ↔ `app/failure.py`와 `lib/failure.ts` · 분위기 목록 ↔ `music.MOOD_LABEL`·`prompts/s6_timeline.md`·`labels.ts` · S3 `EVIDENCE_FIELDS` ↔ S3 프롬프트에 넣는 필드 · 화면 버튼 이름 ↔ 그 이름을 가리키는 안내(`readiness.py` 등 백엔드 포함)와 e2e · 단계가 읽는 키 ↔ 아래 표.
- **`store.py`의 원자적 저장 재시도를 지우지 않는다:** Windows 백신·인덱서 잠금으로 교체가 `PermissionError`를 낸다.
- **프로젝트 ID 형식 검사(`prj_[0-9a-f]{12}`)와 `GET /files`의 폴더 밖 404를 유지한다:** 없으면 data/ 전체가 노출된다.
- **편집은 잠금 안에서:** 사용자 편집은 `orch.edit()`/`edit_with()`로 해야 stale 전파와 `ProjectBusy`(409)가 지켜진다. 음악 합성·AI로 움직이기처럼 파일을 만드는 편집도 잠금 안에서 한다(잠금 밖에서 하면 500·이중 청구가 재현됐다).
- **사장님·매물 사실은 AI가 쓰지 않는다:** 혜택·가격·마지막 장면 대사는 입력값을 그대로 넣는다(`fix_shop_lines`·`fix_listing_lines`). 홍보 모드는 AI 그림·무료 사진을 쓰지 않는다.
- **취미 모드 프롬프트는 그대로 둔다**(`test_hobby_prompts_stay_exactly_the_same`): 모드별 차이는 `app/modes.py`의 `ModeProfile`에 모으고 단계에 `if mode`를 흩뿌리지 않는다.

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
| s7 렌더 | `input`(목표 길이, 자동 점검용), `timeline` | `render` |

기준 구현은 `app/orchestrator.py`의 `_build_pipeline()`이다. 단계 함수는 `async def run(ctx: StepContext) -> <출력>`이고 반환값을 오케스트레이터가 스키마로 검증해 기록한다. `ctx.read(key)`는 선언하지 않은 키를 읽으면 `ContractViolation`을 낸다. `ctx.warn()`은 `project.warnings[step]`에, `StepInputError` 메시지는 사용자에게 그대로 보인다.

### 오케스트레이터 (`app/orchestrator.py`)
- 상태 `idle | running | done | stale | error`. 읽는 키를 쓰는 앞 단계가 모두 `done`일 때만 실행된다(아니면 `StepBlocked`). 내용 조건(`app/readiness.py`의 `not_ready()`)이 모자라면 실행 API는 409, `run_all`은 그 앞에서 멈춘다.
- **Stale 전파:** 단계 출력이 바뀌면(실행이든 편집이든) 뒤 단계는 출력이 있으면 `stale`, 없으면 `idle`. 자동 재실행은 하지 않는다. 필드 단위 전파는 `FIELD_FIRST_READER`(예: `input.user_media`만 바뀌면 S5부터), 매물 정보는 `LISTING_FIELD_READER`.
- 단계 예외는 `status=error` + `errors[step]` + `error_kinds[step]`(`app/failure.failure_kind()`)이고 이전 출력은 보존한다. 화면은 문구가 아니라 kind로 안내를 고른다. `StepBlocked`·`ProjectBusy` 문구는 화면에 그대로 뜨므로 해요체와 `STEP_LABEL`로 쓴다.
- 프로젝트별 `asyncio.Lock`(`ProjectBusy`), 진행은 `EventBus` → SSE. 멈추기는 `orch.cancel()`(그 단계를 error `cancelled`로, FFmpeg도 감시 스레드가 끈다).
- 저장(`app/store.py`): `data/projects/{id}/project.json` 원자적 교체, 버전은 `versions/v{n}.json`, 목록은 SQLite. 일시 상태는 `snapshot=False`.
- 단계마다 LLM 호출을 모아 `project.llm_usage[step]`과 `data/metrics.jsonl`(KPI, 주제·대사는 넣지 않는다)에 남긴다. 프로젝트는 `orch.create_project()`로 만들어야 생성 이벤트가 남는다.

### API·웹 UI (`app/main.py`, `frontend/`)
- 실행 엔드포인트는 `orch.start_run_*()`로 백그라운드 태스크를 띄우고 202를 돌려주며, 진행은 `GET /projects/{id}/events`(SSE)로 받는다. 프론트 `lib/useProject.ts`가 이벤트마다 Project를 다시 읽는다.
- API 서버는 `build_adapters(..., problems=[])`로 관대하게 조립한다: 키가 빠진 LLM·YouTube는 실행 시 `SetupRequired`를 내고 이유는 `/config`의 `setup_problems`로 화면에 뜬다. CLI·스크립트는 바로 실패한다.
- 로컬 보호(`app/guard.py`): Host 제한(DNS rebinding)과 변경 요청의 Origin 검사. 키 설정(`app/keys.py`)은 무료 호출로 확인한 값만 `.env`에 쓰고 어댑터를 다시 만든다. 로그·문제 보고 zip(`app/support.py`)은 키 값을 `[숨김]`으로 지운다.
- 화면: 쉬운 화면 `/`(주제 입력 + 인기 영상) → `/p/{id}`(`components/studio/Studio.tsx`의 ① 아이디어 ② 다듬기 ③ 완성)가 기본이고, 7단계 전문가 화면은 `/p/{id}/pro`(`Workspace.tsx`)다. 설정은 `/settings`.
- 디자인: 색·글자 크기·모서리·그림자는 `app/globals.css`의 `@theme` 토큰으로만 쓴다(직접 색 값·`text-[Npx]` 금지). 밝은 테마는 `:root[data-theme="light"]`와 `system` + `prefers-color-scheme` 두 블록이 토큰 값만 바꾸므로 함께 고친다(영상·그림 위 덮개의 `bg-black`·`text-white`는 예외). 확인 UI는 `components/Confirm.tsx`의 `ConfirmInline` 한 가지, 아이콘은 `components/Icon.tsx` 한 벌. 화면 문구는 해요체·초보자 기준(하네스 `sf-review-rules` 7절)이고 기술 설명은 '자세히'로 접는다. 한글 문장에 `font-mono`를 쓰지 않는다.
- Next 16: 버전에 맞는 문서는 `frontend/node_modules/next/dist/docs/`(`frontend/AGENTS.md`). 동적 `params`는 Promise이고 Suspense 안에서 읽는다. Tailwind v4 전역 CSS는 `@layer base` 안에 둬야 유틸리티가 이긴다.

### 프로젝트 모드 (D21, D23)
`Input.mode`(`hobby` 기본 · `business` 가게 · `listing` 매물)는 만들 때 정하고 바꾸지 않는다. 가게·매물(`modes.is_ad()`)은 실제 사진만 쓰고, 입력값이 근거인 사실 검사(`fact_problems`)와 끝 카드·업로드 체크리스트를 더한다. 둘 다 설정에서 켜야 홈에 나타난다(기본 꺼짐). 매물 계획과 남은 일은 `docs/PLAN_LISTING.md`.

### 어댑터 (`app/adapters/`)
모든 외부 모델·API는 `base.py`의 추상 클래스(`LLMAdapter`, `YouTubeAdapter`, `TTSAdapter`, `ImageAdapter`, `VideoAdapter`) 뒤에 두고 `registry.build_adapters()`가 조립한다. `fake.py`는 결정론적 Fake(테스트·오프라인 개발), `build_adapters(settings, fake_llm=True)`는 LLM만 Fake.
- LLM: `llm/common.JSONLLMAdapter`를 상속해 `_complete()`만 구현한다(스키마 변환·재시도는 공통). Gemini 무료 등급은 모델별 일일 한도라 `GeminiAdapter.model_for(task)`가 대부분의 작업을 경량 모델로 보내고 주 모델은 `s4_strategy`만 쓴다. 모델은 버전 고정 이름(D7). 고급 모드(D13, 선택·유료)는 `RoutedLLM`이 `ADVANCED_TASKS`만 유료 어댑터로 보내고 실패·예산 초과면 무료 경로로 돌아간다.
- 이미지(D12): `IMAGE_MODE`의 소스들을 `image/chain.ImageChain`이 차례로 시도한다(기본 auto: Cloudflare → HF 공개 Space → Pixabay). 장면 동영상(D15)은 Pixabay 동영상, AI로 움직이기(D19 유료 HF·D20 공개 Space)는 `adapters/video_gen/`이고 사용자가 누른 장면만 호출한다.
- 어댑터의 `notices`(한도 소진으로 모델·소스가 바뀐 사실)는 오케스트레이터가 단계 경고로 옮긴다.
- YouTube 호출은 모두 캐시 → `QuotaMeter.check` → 요청 → `record` 순서(쿼터 날짜는 PT).

### 렌더 (`app/adapters/video/ffmpeg.py`, `app/subtitles.py`)
- 장면 k의 시작 `S_k = Σ d_j`(j<k, `d` = 음성 + pad). 전환 길이 `T_k`만큼 클립 k를 앞으로 늘리고 xfade offset은 `S_k − T_k`, 음성은 `adelay`로 정확히 `S_k`. 총 길이 `Σd`. 타이밍을 고칠 때 이 불변식을 유지한다.
- 장면 클립은 병렬 인코딩하고 입력 해시로 캐시한다. 합성은 filter_complex 하나(`render/work/graph.txt`), `cwd=project_dir`로 실행해 `ass=`에 상대 경로를 쓴다. `final.part.mp4`에 만들고 성공해야 `final.mp4`로 바꾼다.
- 자막은 Whisper가 아니라 TTS 어절 타이밍(`*.words.json`)으로 만들고, 문장부호는 원문 대사에서 찾는다.

### LLM 프롬프트
`app/prompts/sN_*.md`의 첫 줄은 `version: x.y`. 레퍼런스 제목·댓글·썸네일 관찰 같은 외부 텍스트는 `wrap_untrusted()`로 감싼다. 프롬프트를 바꾸면 version을 올린다.

## 절대 제약 (`PROJECT_PROMPT.md` §2, §12)
- 기본 경로에서는 과금 API·SDK(OpenAI, Anthropic, ElevenLabs, Replicate, Runway, Vertex 등)를 쓰지 않는다. 예외는 D13의 선택형 고급 모드와 D19의 선택형 영상 만들기뿐이다(영상 만들기는 `app/adapters/video_gen/`, SDK 없이 httpx, 기본 설정에서 만들지 않고 사용자가 누른 장면만 호출한다). 고급 모드: 유료 LLM SDK는 `app/adapters/llm/advanced/` 안에서만 import하고, registry가 `LLM_ADVANCED`가 켜졌을 때만 지연 import한다. `tests/test_cost_guard.py`가 (1) 그 폴더 밖의 유료 SDK import, (2) 기본 설정으로 서버를 띄웠을 때 유료 SDK 모듈 로드, (3) 기본 설정의 유료 어댑터 생성, (4) `pyproject.toml` 의존성 허용 목록을 검사한다. 새 의존성은 허용 목록에 추가하고 이유를 남긴다.
- YouTube: `search.list`(100 units) 전에 캐시를 확인한다. 통계는 `videos.list`/`channels.list`로 50개씩 일괄 조회한다. S2 1회는 450 units 이하여야 하므로(D16) 검색은 합쳐서 4번까지만 한다(해외 시장이 있으면 한국 키워드 2개 + 해외 2개, 없으면 `s2_search.MAX_SEARCH_KEYWORDS` 3개). 일 8,000 units를 넘으면 차단한다. API 키를 여러 개 돌려 쓰는 로직은 금지다.
- 무료 등급만 쓴다. 매일 다시 채워지는 무료 한도(Gemini, Cloudflare, Pixabay)는 괜찮지만, 체험판·소액 크레딧(Hugging Face 등)에 기대는 **기본** 경로는 만들지 않는다(사용자가 충전해 켜는 D19와, 사용자가 동의해 켜는 공개 Space D20은 예외). D22의 그림 Space(`hfspace`)는 매일 채워지는 무료 ZeroGPU 한도이고 영문 프롬프트만 보내며 토큰도 보내지 않아 기본으로 켜 둔다. 결제가 연결된 Gemini 키는 유료 등급이다(`doctor.py --probe-llm`이 402로 감지한다).
- 레퍼런스 영상·이미지·음성은 다운로드하지 않는다(yt-dlp 금지). 메타데이터, 통계, 공개 댓글, 썸네일 URL만 쓴다.
- 사용자 사진을 외부로 보내는 기능은 사용자의 동의(`photo_ok`, 설정의 동의)가 있을 때만 동작한다.

## 개발 환경 메모
개발 PC는 GPU가 없고(Intel UHD 620) RAM이 8GB이며 CPU는 i5-8265U다. 그래서 기본 경로는 "업로드 사진 + Edge-TTS + Gemini 무료 등급"이다(D3, D4). ComfyUI/FLUX/Wan을 로컬에서 실행하는 것은 전제하지 않는다(무거운 작업은 한 번에 하나: 일괄 다시 렌더·클립 미리 만들기도 차례로 돈다). 문서와 사용자 커뮤니케이션은 한국어로 한다.

## 하네스: ShortForge 개발

**목표:** 개선점 찾기 → 구현 → 데이터 사본 검증 → 규칙 검토 → 문서·커밋 → 배포를 같은 방식으로 반복한다.

**호출 조건:** 개선점 확인·진행·실제 검증·배포 같은 개발 흐름 요청을 받으면 `shortforge-dev` 스킬을 사용한다. 단순 질문, 서버 실행·종료, 커밋만 하는 요청에는 직접 처리해도 된다. 여러 줄 수정은 Write로 만든 스크립트 파일로 실행한다(셸 heredoc은 역슬래시가 풀려 파일이 깨졌다). 변경 이력은 `docs/ARCHITECTURE.md` 끝에 있다.
