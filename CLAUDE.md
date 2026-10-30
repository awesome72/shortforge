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
# start.bat(프로덕션 .next)을 띄운 채로 개발할 때: NEXT_DIST_DIR=.next-dev NEXT_PUBLIC_API_BASE=http://127.0.0.1:8001 npx next dev -p 3001
#   (API도 다른 포트로: CORS_ORIGINS='["http://localhost:3001"]' uv run uvicorn app.main:app --port 8001)
#   이때 Next가 tsconfig.json에 .next-dev 경로를 추가하므로 커밋 전에 되돌린다
npx tsc --noEmit && npm run lint                                      # 프론트 검사 (새 clone은 먼저 npx next typegen)
npm run build && npm run e2e                                          # 화면 자동 테스트 (Playwright + Edge, Fake API를 8000에 띄움)
# start.bat이 3000·8000을 쓰고 있으면: NEXT_DIST_DIR=.next-e2e NEXT_PUBLIC_API_BASE=http://127.0.0.1:8010 npx next build
#   → E2E_API_PORT=8010 E2E_WEB_PORT=3010 NEXT_DIST_DIR=.next-e2e npx playwright test (tsconfig.json은 되돌린다)
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
                                          # 실제 YouTube로 S2(+S3 댓글) 실행. 약 410 units, 같은 날 재실행은 0
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
- 화면 자동 테스트(`frontend/e2e/`, `playwright.config.ts`, 3개: 인기 영상 → 주제 채우기, 3단계 흐름 + 전문가 화면, 휴대폰 폭): `webServer`가 `DEV_FAKE_ALL=true`(모든 어댑터 Fake, `build_adapters(fake=True)`)인 API와 `next start`를 띄우고, 데이터는 임시 폴더에 둔다. 브라우저는 `channel: msedge`(Windows 기본 설치, 내려받지 않음). Fake 렌더는 영상 파일을 만들지 않아 미디어 404 콘솔 오류는 무시한다. CI frontend 작업이 빌드 뒤에 돌린다.
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
| s7 렌더 | `input`(목표 길이, 자동 점검용), `timeline` | `render` |

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
- 필드 단위 전파(`orchestrator.FIELD_FIRST_READER`): `input.user_media`만 바뀌면 S5부터 stale이 된다. 전문가 화면의 장면 사진 교체는 `POST /media?attach=false` 뒤 `PATCH assets`로 하며, S6부터 stale이 된다(쉬운 화면은 `/photo`).
- 프로젝트 ID는 `ProjectStore.project_dir()`에서 `prj_[0-9a-f]{12}` 형식을 강제한다. 이 검사가 없으면 `pid=..`로 data/ 폴더 전체가 노출된다(보안 수정 `050baec`). `GET /files/{path}`는 프로젝트 폴더 밖 경로를 404로 막는다. 업로드는 확장자와 함께 파일 시그니처도 검사한다. 웹 UI와 API는 출처가 달라 `<a download>`가 무시되므로 `?download=1`(첨부 응답)을 쓴다.
- 디자인(`ShortForge_Studio_Redesign.html` 기준, 2026-10-22): 어두운 편집실 그래파이트 + 텅스텐(앰버) 포인트. 색은 `app/globals.css`의 `@theme` 토큰으로만 쓰고(이름은 예전 그대로: `canvas`=배경, `surface`=패널, `card`=올라온 면, `sunken`=입력칸, `ink`/`ink-2`/`muted`/`faint`=글자, `accent`=텅스텐, 그 위 글자는 `accent-ink`, `stale`=경고, `role-*`=장면 역할 색) 컴포넌트에 색 값을 직접 쓰지 않는다. 본문 Pretendard(CDN), 숫자·키·타임코드 JetBrains Mono. 작업 화면(`Workspace.tsx`)은 상단 바(프로젝트·비용·쿼터 미터·전체 실행) → 7단계를 편집 클립처럼 보여 주는 파이프라인 타임라인(플레이헤드 = 보고 있는 단계) → 본문 + 오른쪽 인스펙터(9:16 모니터·Project JSON·버전·관리·무료 도구)다. 공통 부품은 `components/ui.tsx`(`Button` primary/ghost/quiet, `Panel`, `Meter`, `Brand`)와 `AppBar.tsx`(홈·설정 상단 바), 단계 머리·바닥은 `StepActions.tsx`의 `StepHeader`(STEP 0n 표시)·`StepActions`(위쪽 선, 오른쪽 주 버튼). 화면 문구 원칙(2026-10-23): 단계 설명(`desc`)은 기술 용어 없이 해요체로 쓰고, API 이름·동작 방식은 `StepHeader`의 `tech`("자세히"로 접힘, `ui.tsx`의 `Details`)에 둔다. 모션·전환·근거 필드 같은 값은 `lib/labels.ts`의 `*_LABEL`로 바꿔 보여 준다. 한글 문장에는 `font-mono`를 쓰지 않는다(고정폭 공백 때문에 자간이 벌어진다). 숫자는 `tabular-nums`. 오디오·비디오는 브라우저 기본 재생기 대신 `components/Media.tsx`(`AudioPlayer`·`VideoPlayer`)를 쓴다. 인스펙터 모니터는 4·5단계에서 고른 장면(`StepProps.scene`/`focusScene`)을 보여 준다. 홈 목록의 진행 막대·썸네일은 `ProjectRow.stages`·`thumb`(저장할 때 갱신)에서 온다. 단축키는 `Workspace.tsx`가 받는다(1~7, Ctrl+Enter는 `StepActions`의 `data-run-primary` 버튼을 누르는 방식이라 저장 전 처리·잠금 조건을 그대로 따른다, Ctrl+K는 `CommandPalette.tsx`). 단계 완료·오류 알림은 `useProject(id, onEvent)`의 SSE 이벤트로 `Toast.tsx`에 띄운다.
- 쉬운 화면(2026-10-29, 기본): 홈 `/`은 주제 한 줄 입력 + `TrendingGrid`(`GET /trending`: `YouTubeAdapter.trending()` = videos.list chart=mostPopular, 1 unit, `TRENDING_TTL` 6시간 캐시, 3분 이하 숏폼 먼저, 분류는 숫자 ID만). 카드는 `YouTubeModal`(youtube-nocookie 임베드, 내려받지 않음)로 크게 보고 '이런 영상 만들기'로 입력을 채운다. '만들기'는 프로젝트를 만들고 `run-all?from=s1&to=s6`(렌더 전까지)을 시작한다. `/p/{id}`는 `components/studio/Studio.tsx`의 3단계 ① 아이디어(1~4단계 자동, 참고 영상·잘 된 이유) ② 다듬기(5~6단계, 대사·그림 느낌·목소리·음악 + 큰 미리보기) ③ 완성(7단계)이고, 7단계 전문가 화면(`Workspace.tsx`)은 `/p/{id}/pro`다. 대사 칸을 벗어나면 `POST /projects/{id}/scenes/{scene}/line`이 그 장면 음성만 다시 만들고 strategy → assets → timeline 순서로 `edit()`해 미리보기가 바로 바뀐다(렌더만 재생성 필요). 그림 느낌·목소리는 input을 고친 뒤 `run-all?from=s5&to=s6`을 자동으로 건다. 대사 카드 왼쪽 `ScenePicture`의 '다른 그림'(`POST .../scenes/{scene}/image`, 생성·검색 소스가 있을 때만)·'내 사진'(`POST /media?attach=false` → `POST .../scenes/{scene}/photo`, 프로젝트 `media/` 안 파일만)은 `main.scene_image_edits()`로 assets와(6단계가 done이면) timeline의 그 장면 image를 `edit_with`로 함께 고친다(6단계 LLM 재실행 없음, 동영상이면 motion static). 6단계가 done이 아닐 때만 화면이 빈 장면이 없으면 `run-all?from=s6&to=s6`을 건다. 대사 저장은 그 장면 칸만 잠그고 화면의 큐로 차례로 보낸다(서버는 동시 편집에 409). 빈 장면이 있고 그림 소스가 있으면 '빈 장면 그림 만들기'(`run-all?from=s5&to=s6`)를 띄운다. S5가 done이면 그림이 빈 장면이 있어도 다듬기를 연다(본인 사진 모드에서 6단계로 못 가던 막다른 길). 장면에 올린 사진(`source=user`, 1단계 목록 밖)은 `reusable_images`가 그림 느낌을 뺀 키(`_photo_key`)로도 남겨, 그림 느낌을 바꿔 S5를 다시 해도 유지된다. 아이디어 단계 진행 상자는 `STEP_SEC`(실측 초)로 전체 진행과 남은 시간을 어림하고, 지난 시간이 max(60초, 처음 예상×2)를 넘으면 '평소보다 오래 걸려요'로 바꾼다. 4단계가 끝나면 아이디어 화면에 장면별 대사를 먼저 보여 준다. 화면 문구는 하네스 `sf-review-rules` 7절(초보자 기준)을 따른다. `/trending`은 키가 없으면(`SetupRequired`) `need_key`와 쉬운 안내를, 다른 오류는 내부 문구 없이 안내만 주고 로그에 남긴다.
- 멈춘 단계 복구: 서버가 실행 중에 꺼지면 `running`이 저장된 채 남는다. API 서버 lifespan이 `orch.recover_interrupted()`로 그런 단계를 error(`orchestrator.INTERRUPTED`)로 바꾸고 이전 출력은 둔다. 화면은 이 문구를 보고 '프로그램이 꺼져 멈췄어요 + 다시 시도'를 띄운다. CLI는 부르지 않는다. 같은 `data/`를 쓰는 서버를 하나 더 켜면(예: start.bat + 개발 API) 다른 쪽에서 실행 중인 단계도 error로 바뀌니 개발 서버는 다른 `DATA_DIR`로 띄운다. 복구는 프로젝트마다 예외를 잡아 서버 시작을 막지 않는다.
- 6단계 미리보기(`components/TimelinePreview.tsx`)는 렌더 없이 timeline의 이미지·음성·배경음악을 브라우저에서 이어 재생한다. 모션은 Web Animations로 FFmpeg zoompan 방향을 흉내 내고, 덕킹과 어절 자막은 없다.
- 배경음악(D14, `app/music.py`): S6 LLM(`s6_timeline`)이 장면 연출과 함께 `mood`(7가지, `MoodName`)를 고르고, `ensure_bgm()`이 `VideoAdapter.make_bgm()`으로 `assets/music/bgm_<mood>_<초>s_<seed>_v<MUSIC_VERSION>.m4a`를 만들어 `timeline.audio.bgm`에 넣는다(순수 파이썬 합성 → FFmpeg로 공간감·페이드·-18 LUFS, 30초 약 3초, 같은 이름이면 재사용). seed는 프로젝트 ID + `variant`. 사용자가 화면에서 고른 음악(`POST /projects/{id}/music`, `.../music/upload`)은 `audio.locked`로 S6 재실행에도 유지된다(끈 상태 포함). 합성 실패는 경고만 남기고 음악 없이 간다. 분위기 목록은 `music.MOOD_LABEL`·`prompts/s6_timeline.md`·프론트 `labels.ts MOOD_LABEL`이 같아야 한다(`test_music.py`가 앞의 둘을 확인). 합성 방식을 바꾸면 `MUSIC_VERSION`을 올린다(v2: 첫 마디는 북 없이 차오르고, 남은 시간이 화음 하나 안이면 으뜸화음을 리듬 없이 울려 끝낸다). `BGM_MODE=off`면 음악 없이 시작한다.
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
- 오케스트레이터가 `project_created`, `step_done`/`step_error`(초, S2·S3 units, S3 근거 수, 단계가 `ctx.stats`에 넣은 값: S4 `s4_attempts`·`s4_retry`(다시 만든 이유 종류, `retry_kind`)), `edited`, `render_done`, `project_duplicated`, `version_restored` 이벤트를 남기고, API는 `download`를 남긴다. Gemini 어댑터는 요청마다 `llm_call`(작업·모델·요청 초·재시도 대기 초·사고 토큰)을 `app.metrics.record_llm_call()`로 남기고, 오케스트레이터가 단계마다 `LLM_CALLS`(ContextVar)에 모아 단계 이름과 함께 기록한다(실패한 단계 포함). `kpi_report.py`가 작업·모델별 속도 표를 보여 준다. 기록 위치는 `data/metrics.jsonl`이며 주제·대사는 넣지 않는다. 프로젝트는 `orch.create_project()`로 만들어야 생성 이벤트가 남는다.

### 어댑터 (`app/adapters/`)
모든 외부 모델·API는 `base.py`의 추상 클래스(`LLMAdapter`, `YouTubeAdapter`, `TTSAdapter`, `ImageAdapter`, `VideoAdapter`) 뒤에 둔다. 조립은 `registry.build_adapters()`가 맡는다.
- `fake.py`: 결정론적 Fake. 테스트와 오프라인 개발에 쓴다. `FakeLLM`은 `task` 이름(`s1_keywords`, `s2_relevance`, `s3_thumbnails`, `s3_factors`, `s4_strategy`, `s4_shorten`, `s4_lengthen`, `s5_image_prompts`, `s5_video_check`, `s6_timeline`)별 `_<task>` 메서드로 응답한다. LLM 호출을 추가하면 여기에도 응답을 추가해야 한다. `FakeTTS`는 rate를 반영해 길이를 바꾼다(길이 보정 테스트용).
- 실제 구현: `llm/gemini.py`, `llm/ollama.py`, `youtube/api.py`, `tts/edge.py`(mp3 + `*.words.json` 어절 타이밍), `video/ffmpeg.py`, `image/{upload,cloudflare,pixabay,pexels,comfyui,chain}.py`. `build_adapters(settings, fake_llm=True)`는 LLM만 Fake로 둔다(측정 스크립트용).
- 어댑터가 `notices`/`drain_notices()`를 가지면(Gemini, ImageChain), 오케스트레이터가 단계가 끝날 때 그 알림을 단계 경고로 옮긴다. 무료 한도 소진으로 모델이나 이미지 소스가 바뀐 사실을 사용자에게 알리는 통로다.
- LLM 어댑터는 `llm/common.JSONLLMAdapter`를 상속하고 `_complete()`만 구현한다. 스키마 변환(`llm_schema`: $ref 펼치기), 코드 펜스 제거, 검증 실패 시 오류를 넣은 2회 재시도는 공통 처리다.
- Gemini 무료 등급 일일 한도는 모델마다 따로다(3.8-flash는 하루 20회). `GeminiAdapter.model_for(task)`가 S1·S2 관련성·S3 썸네일 관찰·S4 대사 줄이기·S5 영문 프롬프트·S6를 `GEMINI_MODEL_LIGHT`로 보낸다. 일일 한도 429(`PerDay`)는 기다리지 않고 경량 모델로 넘긴다. 503 과부하는 경량 모델로 넘길 수 있으면 3초 한 번만 기다리고 넘기며(`SERVER_WAITS_BEFORE_FALLBACK`), 넘길 모델이 없을 때만 5·15·30초를 기다린다. 실패해도 단계가 이어지는 보조 작업(`OPTIONAL_TASKS`: s2_relevance·s3_thumbnails·s5_video_check)은 3초 한 번만 기다리고 실패한다. 과부하가 난 모델은 10분간 건너뛴다(`OVERLOAD_COOLDOWN_SEC`). 주 모델 요청에만 `GEMINI_THINKING_LEVEL`(기본 `low`)을 넣는다. 경량 모델에는 넣지 않는다. low로 바꾼 근거와 Gate 결과는 `config.py` 주석에 있고, 바꾸면 `llm_smoke.py --thinking <값> [--inject]`로 Gate와 요청 시간을 다시 확인한다. 같은 알림은 한 번만 남긴다. `notices`에 남긴 알림은 오케스트레이터가 단계 경고로 옮긴다(D11).
- Gemini: 모델은 버전 고정 이름을 쓴다(D7). `gemini-2.5-flash`는 신규 사용자에게 404를 낸다. 결제가 연결된 프로젝트의 키는 유료 등급이라 쓰지 않는다. 모델 목록에 있다고 호출 가능한 것은 아니므로 `doctor.py --probe-llm`으로 확인한다.
- 이미지(D12): 어댑터는 `ImageRequest`(영문 prompt·seed·검색어 query)를 받아 `ImageResult`(경로·source·provider·credit) 또는 None을 돌려준다. `IMAGE_MODE`에 생성·검색 소스가 하나라도 있으면 `registry.build_image()`가 `image/chain.ImageChain`으로 감싼다. 체인은 `ImageQuotaExceeded`·오류·결과 없음이면 다음 소스로 넘어가고 `notices`를 남긴다. `image/cloudflare.py`: FLUX.2 klein은 **multipart만** 받는다(JSON이면 거부). schnell은 `prompt`·`steps`만 받아 크기·seed를 지정할 수 없다. Neurons는 가격표로 추정해 `neuron_log`(UTC 날짜)에 센다. `stock` 토큰은 `image/pixabay.py`를 가리킨다. Pexels는 2026-10 신규 키 발급이 중단돼 `pexels`로 명시할 때만 쓴다. Pixabay 약관상 검색은 `app/cache`로 24시간 캐시하고, 이미지는 hotlink하지 않고 내려받으며, credit을 남긴다. 사진 어댑터들은 세로 사진을 검색하고 같은 실행에서 쓴 사진은 피한다. S5의 `fetch_image()`는 API의 장면 이미지 다시 만들기(`POST /projects/{id}/scenes/{scene}/image`, seed+1)도 쓴다. S5를 다시 실행하면 `ImageAsset.basis`(장면 묘사+스타일 시드)가 같은 장면은 이전 이미지를 그대로 쓴다(`reusable_images`). 생성 파일 이름은 `image_stem()`(장면·seed·내용 해시)으로 정해, 장면 번호가 바뀌어도 재사용 중인 파일을 덮어쓰지 않는다.
- 이미지 프롬프트(`app/image_prompt.py`, `prompts/s5_image_prompts.md`): 최종 프롬프트는 `build_prompt(장면 영문 묘사, LLM이 옮긴 영문 style, QUALITY)`이고, `clean_image_prompt()`가 글자를 부르는 말(자막·제목·로고·포스터·간판·따옴표 문구), 화면비·레이아웃 말(9:16·숏폼), 부정문 조각(no·without)을 뺀다. `fetch_image()`도 요청 직전에 한 번 더 거른다(예전 프로젝트의 다시 만들기 대비). 계기: S4 style_seed의 '굵은 흰색 자막'을 그대로 붙였더니 FLUX가 장면마다 큰 영문 문구를 그렸다(2026-10-21). FLUX에는 negative 입력이 없고 부정문은 그 대상을 오히려 그린다. S5 LLM은 `style`과 주인공 고정 묘사 `subject`(audience·region에 맞는 인물, 성별·나이·머리·옷)를 함께 만들고, 사람이 나오는 장면에 subject를 그대로 넣어 장면마다 다른 사람이 나오지 않게 한다. 프롬프트 규칙을 바꾸면 `PROMPT_REV`를 올린다: `ImageAsset.rev`가 낮은 **생성** 이미지는 S5 재실행 때 재사용하지 않는다(사진·사용자 이미지는 그대로). 품질 문구는 `quality_for(style)`가 그림체(일러스트·수채 등이면 `QUALITY_ILLUSTRATION`, 아니면 사진)에 맞춰 고른다: 일러스트 스타일에 다큐 사진·35mm 문구를 붙였더니 한 영상 안에서 그림체가 섞였다. LLM이 subject에 성별을 빼면("a Korean person …") 장면마다 다른 사람이 나와 `fix_subject()`가 타깃의 성별 단서나 seed로 채우고 `apply_subject()`가 장면 프롬프트도 맞춘다(PROMPT_REV 4). subject만 바꾸면 장면에 남은 "her neck"·검색어 "tired woman sofa" 때문에 성별이 섞여, `align_gender()`가 장면 prompt·query의 반대 성별 단어·대명사도 subject 성별로 바꾼다(두 성별이 함께 있는 장면은 그대로, PROMPT_REV 5). Cloudflare 기본 크기는 864×1536(720×1280과 같은 6타일 = 156 Neurons). klein 9B·FLUX.2 dev는 장당 약 1,364·4,500 Neurons라 무료 한도로 쓰지 않는다.
- 장면 동영상(D15): 장면 소스는 확장자로 사진/동영상을 가른다(`media.VIDEO_EXT`·`is_video_path`, 프론트 `Media.isVideo`·`SceneMedia`). 스키마는 그대로다(`ImageAsset.source`가 user·stock이고 `path`가 .mp4). 업로드는 `is_video` 시그니처 검사 후 1MB 조각으로 저장한다(300MB). `image/pixabay_video.py`는 `/api/videos/`를 24시간 캐시(키에 `PER_PAGE` 포함)하고, `rank()`가 길이(4~60초) → 관련도(태그에 있는 검색어 단어 수 − 사람 태그 감점(사람 없는 장면) − 검색어에 없는 행사·폐허 태그 감점) → 태그 중 검색어 비율 → 세로 순으로 줄 세운 뒤 `choose()`가 상위 `TOP_K`(3) 안에서 seed 자리부터 안 쓴 영상을 고른다(쓴 영상을 먼저 빼고 고르면 자리가 밀려 상위를 건너뛰었다). 그 뒤 `app/video_pick.judge()`가 상위 `VISION_TOP`(8)개 썸네일을 이미지를 볼 수 있는 LLM(`s5_video_check`, Gemini 경량)에 URL로 한 번 넘겨 fits(0~2)·person을 받아 다시 줄 세운다(사람이 없어야 하는 장면이면 사람 감점, 실패·이미지 미지원이면 태그 순서). 체인의 동영상 소스에는 `build_adapters`가 같은 LLM을 넣는다. 5단계는 내려받지 않는 미리보기 흐름이다: `POST .../scenes/{scene}/videos`가 `preview()`(Pixabay tiny 영상 주소, 약관상 직접 재생 허용)를 돌려주고, `POST .../video/select {id}`가 캐시된 검색 결과에서 그 영상을 찾아(`find`) 받고 `assets/video/{scene}_pixabay_{id}.mp4`로 적용한다(이미 받았으면 재사용). 테스트는 `app.state.video_transport`에 가짜 서버를 넣는다. 받은 원본은 `conform()`이 세로 1080×1920·30fps·무음·앞 20초로 한 번 바꾼다. 자르는 자리는 `crop_filter(focus_x)`로, 썸네일 판정(`VideoCheck.focus`, 프롬프트 v1.1)이 준 주요 피사체 가로 위치를 가운데에 두되 화면 밖으로 나가지 않게 한다(판정이 없으면 가운데). 판정 결과는 캐시를 바꾸지 않게 복사본에만 붙이고(`focus_x`), 5단계는 `video/select {id, focus_x}`로 넘긴다. 이미지 방식 `video`는 체인 안에서 `ImageRequest.person`(`image_prompt.has_person`)이 참인 장면과 그림체가 일러스트·수채화(`is_illustrated(prompt)`)인 프로젝트를 건너뛰고(`skip_person`), 5단계 `candidates?kind=video`는 `registry.pixabay_video(skip_person=False)`로 사람 장면도 찾는다(`/config`의 `stock_video`). 렌더 `_clip`은 동영상이면 zoompan 대신 `fps,scale,crop,tpad=stop_mode=clone`(짧으면 마지막 프레임 정지)이고, S6는 동영상 장면의 움직임을 `static`으로 둔다. 커버·업로드 체크리스트(`publish._count`)도 동영상을 따로 센다.
- `image/comfyui.py`는 원격 GPU 장비의 ComfyUI API(`/prompt` → `/history` → `/view`)를 쓴다. 워크플로는 `{{자리표시자}}`가 있는 API 형식 JSON이며, 값 전체가 자리표시자면 숫자 타입을 그대로 유지한다. 개발 PC에는 GPU가 없어 `tests/test_comfyui.py`의 가짜 서버로만 검증했다.
- YouTube 어댑터의 모든 호출은 캐시 → `QuotaMeter.check` → 요청 → `record` 순서다. 쿼터 날짜는 PT 기준(`app/quota.pt_today`)이다. 네트워크 오류는 쿼터를 기록하지 않고, 서버 응답(오류 포함)은 기록한다.

### 렌더 파이프라인 (`app/adapters/video/ffmpeg.py`, `app/subtitles.py`)
- 장면 k의 시작 시각은 `S_k = Σ d_j`(j<k, `d` = 음성 + pad)이다. 전환 길이 `T_k`만큼 클립 k를 앞으로 늘리고, xfade offset은 `S_k − T_k`, 음성은 `adelay`로 정확히 `S_k`에 놓는다. 총 길이는 `Σd`이다. 타이밍을 고칠 때는 이 불변식을 유지한다.
- FFmpeg/ffprobe는 `app/media.run()`으로만 실행한다. asyncio 서브프로세스가 아니라 스레드 기반 subprocess다. Windows `uvicorn --reload`의 SelectorEventLoop가 asyncio 서브프로세스를 지원하지 않기 때문이며, `tests/test_media_loop.py`가 이를 지킨다.
- 장면 클립은 병렬(`workers` = 코어 수의 절반)로 zoompan 인코딩한다. 클립 이름은 입력(이미지 파일 크기·수정 시각, 필터, 인코딩 설정, `CLIP_VERSION`)의 해시라서 같은 클립이 있으면 다시 만들지 않고, 쓰지 않게 된 클립은 렌더 끝에 지운다. 클립을 만드는 방식을 바꾸면 `CLIP_VERSION`을 올린다. `clip_preset`을 ultrafast로 두면 클립은 빨라지지만 최종 SSIM이 0.987로 떨어져 기본값은 최종 preset과 같다. 합성은 filter_complex 하나로 처리한다(`render/work/graph.txt`에 저장됨). ffmpeg는 `cwd=project_dir`로 실행해서 `ass=` 필터에 상대 경로를 쓴다(Windows 경로 이스케이프를 피하기 위함).
- 영상 마감(2026-10-24): 색 보정 `GRADES[RENDER_GRADE]`는 (장면 클립 단계, 합성 단계) 한 쌍이다. 대비·톤(`lutyuv`)·비네팅은 병렬·캐시되는 클립 단계에, 그레인(`noise`)과 끝 페이드(`fade`/`afade`, `END_FADE_SEC`)만 합성 단계에 둔다. 합성 단계에 `colorbalance`(RGB)·`vignette`를 두면 30초 영상 합성이 3배 느려졌다. zoompan은 코사인 가감속이고 세기는 `MAX_MOTION`(0.12)으로 자른다. `slide` 전환은 크로스페이드로 바꿔 쓴다(S6도 slide를 fade로 고친다). 장면 클립 프레임 수는 **올림 + 1**이다: 반올림으로 한 프레임 모자라면 다음 컷(1프레임 xfade)이 시작하기 전에 앞 클립이 끝나 xfade가 영상을 거기서 끊었다(`test_cut_transitions_keep_video_to_the_end`). 자막 글꼴은 `subtitles.find_font()`가 고르고(auto·Malgun Gothic이면 Pretendard → Noto Sans KR → 나눔고딕 → 맑은 고딕), 렌더가 그 파일을 `render/work/fonts`로 복사해 `ass=...:fontsdir=`로 넘긴다(사용자 폴더 글꼴은 libass가 못 찾는다). 자막 스타일은 `ASS_STYLES`·`ASS_INTRO`(등장 효과)이고 숫자 어절만 `\1c`로 포인트 색을 준다.
- 영상 마감 3차(2026-10-24): 렌더의 `_overlays()`가 화면 장식만 ASS에 더한다(SRT 제외): 순서로 시작하는 대사(`subtitles.badge_number`)의 번호 배지(`badge`, BorderStyle 3 상자), 채널 이름(`BRAND_NAME`, `POST /settings/brand`)이 있으면 마지막 `END_CARD_SEC`(2.4초)에 화면을 덮는 반투명 사각형(`dim`, ASS 그림 `\p1`, 맨 아래 층)과 `brand` 글자. 목소리는 합성 단계에서 `VOICE_CHAIN`(highpass·presence EQ·acompressor)을 거친다. 장면 클립 동시 개수는 `_workers_for_memory()`가 남은 메모리(`media.available_memory_mb`)로 줄인다(`RENDER_WORKERS`를 정했으면 그대로).
- 내보내기 전 점검·렌더 버전(2026-10-26): 렌더 끝에 `_measure()`가 완성 영상의 소리만 한 번 읽어(ebur128·silencedetect, 몇 초) 통합 음량과 긴 무음을 재고, `subtitles.too_wide()`가 화면 폭을 넘을 자막을 어림한다. S7의 `render_checks()`가 길이(목표 ±15%, 5단계 보정과 같은 기준)·음량(−14±1.5 LUFS)·무음(처음·끝 0.5초 제외)·자막 폭을 `render.checks`에 남기고, 실패 항목은 단계 경고로도 띄운다. 측정하지 못한 항목은 빼고 판정한다. `render.quality`는 `s7_render.RENDER_QUALITY`(렌더 결과가 눈에 띄게 달라지는 변경을 하면 올린다)이고, 값이 없는 예전 렌더는 `rendered_quality()`가 `subs.ass`의 흔적(`Style: dim` → 3, `\blur` → 2)으로 어림한다. `GET /projects/{id}`의 `render_outdated`가 참이면 7단계에 "새 방식으로 다시 렌더"가 뜬다. 숫자 강조(`_accent_numbers`)는 줄(`\N`)마다 따로 칠한다(공백으로만 나누면 다음 줄까지 칠해졌다).
- 예전 방식 일괄 다시 렌더: `GET /renders/outdated`가 s7 done이고 `rendered_quality < RENDER_QUALITY`인 프로젝트 ID와 진행 상황(`bulk`)을, `POST /renders/outdated/rerender`가 그 프로젝트들의 7단계만 **한 개씩 차례로** `orch.run_step`으로 돌린다(동시에 돌리면 RAM 8GB가 버티지 못한다). 홈 화면(`OutdatedRenders`)이 3초마다 진행을 본다.
- 밝은 장면 자막 판(2026-10-27, `RENDER_QUALITY` 4): 렌더의 `_mark_bright()`가 장면마다 자막 스타일의 띠(`subtitles.caption_band`)를 화면 크기로 맞춘 사진(동영상은 0.5초 프레임)에서 `band_luma()`(signalstats YAVG)로 재고, `BRIGHT_LUMA`(150) 이상이면 그 장면 자막의 `Cue.plate`를 켠다. `to_ass()`는 판을 맨 아래 층에 글자 폭 어림(`_glyph_width`) 크기 사각형을 `\blur18`·50% 불투명으로 그린다(장면 클립을 다시 인코딩하지 않는다). 커버도 같은 방법이다. 측정값은 render.log의 `caption luma`.
- 자막 한 줄 글자 수(2026-10-29, `RENDER_QUALITY` 5): 렌더 `_cues()`는 timeline의 `max_chars_per_line`(14)을 그대로 쓰지 않고 `subtitles.style_max_chars(style, …)`로 스타일 크기에 맞춰 줄인다(1080 기준 한글 폭: body 12, emphasis 11, hook_bold 9). 14자 그대로면 렌더 13개 중 5개가 자막 폭 점검에 걸렸다. `ASS_STYLES` 크기를 바꾸면 이 값도 바뀐다.
- 장면 클립 미리 만들기(2026-10-30, 선택, 기본 끔): `PRERENDER_CLIPS`(`POST /settings/prerender`, 설정 화면)가 켜져 있으면 오케스트레이터가 편집·S6 완료 때 `schedule_prerender()`로 프로젝트당 작업 하나를 잡고, 편집이 `PRERENDER_DELAY_SEC`(8초) 멈추면 `VideoAdapter.prepare_clips()`가 s6 done인 timeline의 없는 클립을 한 개씩 `media.run(low_priority=True)`로 만든다(전체에서 한 번에 하나). 클립 이름은 렌더와 같은 `_clip_command()`라 렌더가 그대로 재사용한다. `media.run(should_stop=...)`의 감시 스레드가 렌더·편집이 시작되거나(`any_busy`, 다른 프로젝트 포함: RAM 8GB) 새 편집·삭제·설정 끄기가 오면 진행 중인 FFmpeg도 바로 끝낸다. 삭제는 `_stop_prerender()`로 끝나기를 기다린다(FFmpeg가 파일을 쥐고 있으면 폴더를 지우지 못해, `store.delete`는 project.json이 없어도 목록 행이 있으면 다시 지울 수 있다). 임시 파일은 `pre_clip_*`이고 렌더의 `_clip`도 그사이 클립이 생겼으면 덮어쓰지 않는다. 다 만들면 현재 계획 밖의 옛 클립을 지운다. 실패해도 렌더가 대신 만든다. 실측: 완성 110.9초 → 31.9초(클립 57.2초 → 0).
- 커버(썸네일): `POST /projects/{id}/cover`가 첫 장면 이미지 + 커버 문구(기본 4단계 제목, `{title}`로 바꾸면 `render/cover_title.txt`에 저장, "/"는 줄바꿈, 비우면 제목으로) 한 장을 `VideoAdapter.make_cover()`로 만든다(영상과 같은 클립 색 보정·글꼴, `cover` 스타일은 아래쪽 1/3, 제목 줄바꿈은 `wrap_title()`이 자막 규칙으로). 파일 이름은 `publish.cover_path()`의 해시(제목·이미지·수정 시각·`COVER_VERSION`)라 바뀌면 새로 만들고, 업로드 도구(`GET .../publish`의 `cover`)에 있을 때만 보인다. Project JSON에는 넣지 않는다.
- 목소리(`Input.voice`: auto·female·male): `narrator_gender()`는 고른 목소리 → 재사용하는 생성 그림 속 주인공(`gender_in`) → 타깃의 성별 단서 → seed 순서로 정하고, `fix_subject(..., gender)`가 새 그림의 주인공 성별도 맞춘다(대명사까지 바꾼다). 한국어 목소리는 `KO_VOICES`(여성 SunHi, 남성 HyunsuMultilingual: InJoon은 초당 5.5자로 느려 속도를 +25%까지 올려야 했다). 설정의 `TTS_VOICE`가 기본 목소리 중 하나가 아니면 '자동'일 때 그 목소리를 쓴다.
- 그림체(`Input.visual_style`: auto·photo·cinematic·illustration·watercolor): S5가 `apply_visual_style()`로 고른 그림체 문구를 앞에 두고 LLM 스타일에서는 색감·조명만 남긴다. `image_basis()`에 그림체가 들어가 바꾸면 이미지를 새로 만들고, `FIELD_FIRST_READER`로 S5부터만 stale이 된다.
- 장면 길이는 말 길이로 잡는다(2026-10-29): Edge-TTS mp3는 마지막 어절 뒤 약 0.9초가 조용해(음성 시간의 19%) 대사 사이가 1초 넘게 비었다. `edge.speech_length()`가 마지막 어절 끝 + `SPEECH_TAIL`(0.25초)을 `TTSResult.speech_sec`·`VoiceAsset.speech_sec`에 남기고, S5 길이 맞추기·S6 장면 길이·대사 한 줄 바꾸기는 `VoiceAsset.length`(없으면 파일 길이 `duration_sec`)를 쓴다. 파일이 장면보다 길어도 겹치는 부분은 조용한 소리라 렌더(adelay·amix)는 그대로다. S4 `CHARS_PER_SEC`(6.8)도 이 기준의 실측이다(파일 길이 기준이면 5.9).
- 자막은 Whisper가 아니라 TTS 어절 타이밍으로 만든다. Edge-TTS 7.x는 `boundary="WordBoundary"`를 명시해야 한다. 타이밍에 문장부호가 없으므로 원문 대사(`caption.text`)에서 쉼표·마침표 위치를 찾아 끊는다. 침묵 구간은 강제 구분으로, 그 너머로 자막을 합치지 않는다. 긴 구절은 `_balanced_split()`이 (가장 긴 줄 + 뜻이 갈리는 자리 감점)으로 나누고, 감점을 피하려면 한 줄 더 쓰는 것도 비교한다: 수·관형사·서수("한 / 장", "두 / 번째"), 꾸미는 말("같은", "-은/는"), "수/때/것" 앞에서는 끊지 않는다. 한 줄 안에 합쳐진 구절 사이에는 쉼표를 남긴다.

### LLM 프롬프트
`app/prompts/sN_*.md`의 첫 줄은 반드시 `version: x.y`여야 한다(`app/llm.load_prompt`가 검사함). 레퍼런스 제목·댓글 같은 외부 텍스트는 `wrap_untrusted()`로 감싼다. S3는 선택된 영상을 가리키지 않는 evidence를 지우고, 근거가 없어진 요인은 버린다. `hook`/`visual` 요인은 항상 `estimated`로 둔다. 근거 필드 허용 목록(`s3_factors.EVIDENCE_FIELDS`)은 S3 프롬프트에 실제로 넣는 필드와 같아야 한다. 둘은 함께 바꾼다.
- 썸네일 비전 분석(F-3.3): `LLMAdapter.supports_images`가 참이면 S3가 먼저 `s3_thumbnails`(경량 모델, 1회, 최대 8장)로 썸네일을 관찰하고 `thumbnail` 필드로 블록에 넣는다. 썸네일은 **내려받지 않고** URL을 `generate_json(..., images=[url])`로 넘겨 Gemini가 직접 읽는다(`types.Part.from_uri`). 관찰 결과도 이미지 속 외부 텍스트라 `wrap_untrusted()`로 감싼다. 실패하면 경고만 남긴다. Ollama 어댑터는 이미지를 받지 않는다.
- S5는 `tts_script()`로 대사를 정리하되 숫자는 바꾸지 않는다(자막이 TTS 어절에서 나오므로). 음성은 이미지 쪽(영문 프롬프트 → 이미지)과 `TaskGroup`으로 동시에 만들고(서로 의존하지 않는다), 동시에 3개씩 합성하며, 합계가 목표 ±15%를 벗어나면 `fit_rate()`로 rate를 정해 한 번 다시 합성한다(−10%~+25%: 더 늦추면 늘어져 들린다). 그래도 짧으면 S6가 마지막 장면 끝을 최대 2초 늘려(`MAX_END_EXTRA`) 메운다(장면마다 나눠 늘리면 대사 사이 쉼이 다시 벌어졌다). 최종 오디오는 `loudnorm`으로 −14 LUFS에 맞춘다. S6는 규칙 기반 타임라인이 경로·길이를 정하고, LLM(`s6_timeline`)은 모션·전환·자막 스타일만 덮어쓴다. 첫 장면 전환은 항상 cut이다.
- 해외 레퍼런스(D16): `SEARCH_MARKETS`(`언어:지역`, 기본 `en:US,ja:JP`, 비우면 입력의 지역만)의 시장마다 S1이 현지 검색어(`Input.world_keywords`, 번역이 아니라 현지에서 검색할 말)를 만들고, S2가 시장별로 search + `trending()`(1 unit, 해외만, 주제와 관련 있다고 판정된 것만 남긴다)을 합친다. 점수(`build_refs`)는 시장 안에서만 낸다(조회수 규모가 달라서). `Ref.market`(비면 입력의 지역)·`Ref.title_ko`(관련성 판정 호출에서 함께 받는 번역, 화면 표시와 S4 유사도 검사용). 선택은 `_choose()`: 한국 3 + 해외 3(시장을 번갈아), 채널당 2개, `MIN_REF_VIEWS`(1만) 미만은 뒤로. 해외 검색 실패·쿼터 차단은 경고만 남기고 한국 후보로 진행한다. S1의 해외 검색어 실패도 키워드가 이미 있으면 경고로 끝나고, 주제가 바뀌면(`Input.world_topic`과 다르면) 다시 만든다. S4는 제목 유사도를 해외 제목의 번역과도 비교한다(단어 비교라 번역한 베끼기는 원문으로 잡히지 않는다).
- 영상 공식(포맷 패턴 카드): 단계 계약(출력 키 하나)을 지키려고 `Factor`에 `name="format"`과 `hook_type`·`structure`·`emotion`·`ending`·`scope`를 더했다. LLM 응답은 `FactorDraft`(scope 없음: 코드가 계산하고, 빈 문자열 enum은 Gemini 스키마 위험)이고, `s3_factors._mark_patterns()`가 근거 영상의 `Ref.market`으로 `scope`(shared·overseas·local)를 계산해 `Factor`로 만든다(한국·해외 영상을 모두 골랐고 서로 다른 영상 2개 이상이 근거일 때만, 항상 estimated, 최대 3개, 시작·전개가 빈 카드는 버린다). scope는 부재의 증거가 아니라 LLM이 인용한 영상 기준이라 화면 문구도 '보였어요'로 쓴다. 클래스 설명문은 LLM 스키마에 실려 나가므로 응답 모델에는 주석을 쓴다. S4는 `factor_line()`으로 요인·카드를 `wrap_untrusted`로 감싸 넣고 그중 하나로 구성을 짠다.
- S1은 키워드를 3개만 쓴다(해외 시장이 있으면 2개. S2가 그만큼만 검색하므로, 더 만들면 매번 '제외했다' 경고만 남았다). 사용자는 5개까지 고칠 수 있다. 키워드는 2~3단어의 넓은 검색어여야 한다. "…후기", "…변화"처럼 좁은 키워드는 최근 90일 숏폼 검색 결과가 0개가 되기 쉽다. S2는 관련 후보가 하나도 없으면 점수 순으로라도 고르고, 레퍼런스가 4개 미만이면 경고한다.
- S4는 대사 분량을 약 6.8자/초(Edge-TTS 실측, 말 길이 기준)로 검사해 너무 길면 줄이게 한다. 총량 기준은 `char_budget()` = (목표 길이 − 장면 여백 0.2초 × 장면 수 − 마지막 장면 추가 여백 `LAST_SCENE_EXTRA_PAD` 0.4초) × 6.8이다(영상 길이 = 말 + 여백). 마지막 장면 여백은 S6가 더하며(렌더의 끝 페이드 0.5초가 마지막 말을 덮지 않게), S5 길이 맞추기도 같은 값을 뺀다. S5의 속도 보정은 그다음 안전망이다: 길 때는 `OVER_TOLERANCE`(5%)만 넘어도 빠르게 맞추고, 짧을 때는 15%까지 두고 S6 여백이 메운다(2026-10: 30초 목표에 33.4초가 그대로 나갔다).
- S2는 점수 상위 후보(해외를 찾지 않으면 20개, 찾으면 한국 14 + 시장당 6 + 차트 4)를 LLM(`s2_relevance`)으로 관련성 판정한다. 실패해도 S2를 실패시키지 않는다. S4는 `review()`로 (치명/교정/참고) 문제를 나누고, 치명·교정 문제는 `[수정 요청]`을 붙여 최대 3회 재생성한다. 교정 문제가 대사 길이뿐이면 재생성하기 전에 `shorten_lines()`가 긴 대사만 경량 모델(`s4_shorten`)로 줄인다(주 모델은 재생성 때 글자 수를 잘 못 맞춘다). 길이 교정 요청에는 지금 대사를 함께 적는다. 대사 총량이 권장(`char_budget()`)보다 15% 넘게 짧으면 재생성 루프가 끝난 뒤 `lengthen_lines()`가 경량 모델(`s4_lengthen`)로 훅을 뺀 짧은 장면만 한 번 보강하고, 실패해도 주 모델로 다시 만들지 않고 경고만 남긴다(무료 한도 보호). 2026-10 실측에서 126~146자 대사는 5단계가 −17~−20%로 늦춰 늘어져 들렸다. 분석에 없는 요인 참조는 경고 없이 지운다(`drop_unknown_refs`). 사용자 입력에는 쓸 수 있는 factor 이름 목록을 넣는다. 프롬프트를 바꾸면 첫 줄 `version:`을 올린다.

## 절대 제약 (`PROJECT_PROMPT.md` §2, §12)
- 기본 경로에서는 과금 API·SDK(OpenAI, Anthropic, ElevenLabs, Replicate, Runway, Vertex 등)를 쓰지 않는다. 예외는 D13의 선택형 고급 모드뿐이다: 유료 LLM SDK는 `app/adapters/llm/advanced/` 안에서만 import하고, registry가 `LLM_ADVANCED`가 켜졌을 때만 지연 import한다. `tests/test_cost_guard.py`가 (1) 그 폴더 밖의 유료 SDK import, (2) 기본 설정으로 서버를 띄웠을 때 유료 SDK 모듈 로드, (3) 기본 설정의 유료 어댑터 생성, (4) `pyproject.toml` 의존성 허용 목록을 검사한다. 새 의존성은 허용 목록에 추가하고 이유를 남긴다.
- YouTube: `search.list`(100 units) 전에 캐시를 확인한다. 통계는 `videos.list`/`channels.list`로 50개씩 일괄 조회한다. S2 1회는 450 units 이하여야 하므로(D16) 검색은 합쳐서 4번까지만 한다(해외 시장이 있으면 한국 키워드 2개 + 해외 2개, 없으면 `s2_search.MAX_SEARCH_KEYWORDS` 3개). 일 8,000 units를 넘으면 차단한다. API 키를 여러 개 돌려 쓰는 로직은 금지다.
- 무료 등급만 쓴다. 매일 다시 채워지는 무료 한도(Gemini, Cloudflare, Pixabay)는 괜찮지만, 체험판·소액 크레딧(Hugging Face 등)에 기대는 경로는 만들지 않는다. 결제가 연결된 Gemini 키는 유료 등급이다(`doctor.py --probe-llm`이 402로 감지한다).
- 레퍼런스 영상·이미지·음성은 다운로드하지 않는다(yt-dlp 금지). 메타데이터, 통계, 공개 댓글, 썸네일 URL만 쓴다.

## 개발 환경 메모
개발 PC는 GPU가 없고(Intel UHD 620) RAM이 8GB이며 CPU는 i5-8265U다. 그래서 기본 경로는 "업로드 사진 + Edge-TTS + Gemini 무료 등급"이다(D3, D4). ComfyUI/FLUX/Wan을 로컬에서 실행하는 것은 전제하지 않는다. 문서와 사용자 커뮤니케이션은 한국어로 한다.

## 하네스: ShortForge 개발

**목표:** 개선점 찾기 → 구현 → 데이터 사본 검증 → 규칙 검토 → 문서·커밋 → 배포를 같은 방식으로 반복한다.

**호출 조건:** 개선점 확인·진행·실제 검증·배포 같은 개발 흐름 요청을 받으면 `shortforge-dev` 스킬을 사용한다. 단순 질문, 서버 실행·종료, 커밋만 하는 요청에는 직접 처리해도 된다.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
| --- | --- | --- | --- |
| 2026-10-29 | Harness v2로 처음 구성 (서브에이전트 위임: sf-analyst·sf-reviewer·sf-verifier·sf-releaser, 스킬 4개) | 전체 | 반복되던 개선·검증·배포 절차와 그동안의 주의점을 고정 |
| 2026-10-29 | 여러 줄 수정 스크립트는 Write로 만든 파일로 실행(셸 heredoc 금지), sf-verify의 tsconfig 정리를 JSON 기반으로 | skills/shortforge-dev, skills/sf-verify/scripts | heredoc에서 역슬래시가 풀려 파일이 세 번 깨짐, next dev가 tsconfig를 한 줄로 다시 써 줄 단위 정리가 파일을 비움 |
| 2026-10-29 | 초보자 기준 사용성 원리 추가(결정 수·내부 용어·결과 크기·즉시 미리보기·막다른 길), 분석에 사용성 근거, 검증에 '초보자 흐름 걷기', 큰 화면 개편은 시안 먼저 | skills/sf-review-rules·sf-verify·shortforge-dev, agents/sf-analyst | "단계를 3개로, 초보자도 쉽게, 영상 크게, 바로 미리보기" 피드백 — 기술 수치·규칙만 보던 하네스가 사용성을 판단할 기준이 없었다 |
