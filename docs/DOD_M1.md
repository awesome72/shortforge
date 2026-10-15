# M1 완료 기준(DoD) 점검표

`PROJECT_PROMPT.md` §10의 항목을 근거와 함께 점검한다. 점검일은 2026-10-15이고, 기준 장비는 i5-8265U, RAM 8GB, GPU 없음이다.

| # | 기준 | 상태 | 근거 |
|---|---|---|---|
| 1 | `.env`에 키 2개만 넣고 한 번에 7단계 전체가 실행된다 | **부분** | `setup.bat`(1회)과 `start.bat`으로 API·웹 UI가 뜨는 것까지 실제 실행으로 확인했다(127.0.0.1 바인딩, 종료 시 프로세스 정리). Docker는 개발 PC에 없어 쓰지 않는다(D10). **실제 LLM으로 7단계를 끝까지 돌리는 확인은 남았다**(Gemini 키 결제 문제, D7) |
| 2 | S2 1회 실행 쿼터 ≤ 400 units | ✅ | 실측 303 units, 같은 날 재실행 0 units (`scripts/youtube_smoke.py`). `tests/test_youtube.py`에서 검증 |
| 3 | 모든 단계 출력이 스키마를 통과하고, 실패하면 원인을 표시한다 | ✅ | Pydantic `validate_assignment`, LLM 출력 검증 실패 시 2회 재시도, `errors[step]`을 UI·CLI에 표시. 메시지가 없는 예외는 발생 위치를 붙인다 |
| 4 | 앞 단계를 편집하면 뒤 단계가 `stale`이 된다 | ✅ | `tests/test_orchestrator.py`, `tests/test_api.py`, 브라우저 E2E. 필드 단위 전파(사진만 바뀌면 S5부터) |
| 5 | CPU만으로 30초 영상 렌더 ≤ 3분 | ✅ | TTS와 렌더를 합쳐 37.9~51.3초 (`scripts/render_spike.py`) |
| 6 | `LLM_MODE=ollama`면 외부 LLM 호출 없이 동작한다 | **미검증** | 어댑터와 구조화 출력은 가짜 서버 테스트로만 확인했다. Ollama가 설치되어 있지 않다 |
| 7 | 비용이 발생할 수 있는 코드 경로가 0개다 | ✅ (조건부) | `tests/test_cost_guard.py`: 과금 SDK import 금지, 의존성 허용 목록. 단 **키가 결제 연결 프로젝트 소속이면 Gemini 호출이 과금된다** → `doctor.py --probe-llm`으로 감지(D7) |
| 8 | `scripts/doctor.py`가 전 항목을 통과한다 | ✅ | `setup.ps1` 안에서 실행해 "통과". Gemini는 목록 확인만 하는 WARN이고, 실제 호출 확인(`--probe-llm`)은 402다 |

## M1 Gate (PROJECT_PLAN Step 9)

| 기준 | 상태 |
|---|---|
| DoD 통과 | 8개 중 6개 통과, 1번 부분, 6번 미검증 |
| 베타 사용자 10명이 각 1편 이상 완주 | 대기 — `docs/BETA_GUIDE.md`, `docs/BETA_FEEDBACK.md` 준비됨. KPI는 `data/metrics.jsonl` → `scripts/kpi_report.py` |

## 보안 점검 (Step 9-3)

| 항목 | 결과 |
|---|---|
| 경로 탈출 (`/files/{path}`) | 차단, 테스트 있음 |
| **프로젝트 ID 경로 탈출** | **발견 후 수정.** `pid=..`로 `data/shortforge.db`가 내려받아졌다. ID 형식을 강제해 막았다(커밋 `050baec`) |
| 업로드 위장 파일 | 시그니처 검사 추가 (JPEG/PNG/WEBP), 25MB 제한, 파일명 정리 |
| 프롬프트 인젝션 | 외부 텍스트를 `<untrusted>`로 감싸고 태그 위조를 막는다. 실제 모델 확인(`llm_smoke.py --inject`)은 키 교체 후 진행 |
| 네트워크 노출 | API·웹 UI 모두 127.0.0.1에만 바인딩. CORS는 localhost:3000만 허용 |
| 비밀값 | `/config`에 키 없음, `.env`는 git 제외, 커밋 이력에서 키 패턴 검사 |
| FFmpeg 인자 | 셸을 거치지 않고 리스트 인자로 실행. 자막 텍스트는 ASS 파일로만 들어가고 `{}`·`\`는 이스케이프한다 |
| 남은 위험 (수용) | 인증 없는 로컬 앱이다. 다른 웹사이트가 본문 없는 POST(실행 요청)를 보낼 수는 있지만, 프로젝트 ID가 무작위 48비트이고 응답은 CORS로 읽을 수 없다. `input.user_media`에 PC의 임의 이미지 경로를 넣으면 렌더에 쓰인다(로컬 단일 사용자 전제) |
