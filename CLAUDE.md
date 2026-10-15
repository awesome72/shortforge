# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트

ShortForge — 사용자 입력(주제·타깃·톤)으로 YouTube 레퍼런스를 분석해 30초 숏폼(MP4 + SRT)을 만드는 7단계 파이프라인. 모든 단계는 **비용 ₩0**(무료 쿼터 + 로컬 오픈소스)으로만 구성한다.

문서 우선순위: `PRD.md`(무엇·왜, 충돌 시 최우선) > `PROJECT_PROMPT.md`(구현 지시서: 계약·스키마·API·DoD) > `PROJECT_PLAN.md`(Step별 실행 계획과 각 Step의 Gate·진행 상태) > `docs/DECISIONS.md`(확정된 결정 D1~D5). Step을 끝내면 `PROJECT_PLAN.md`의 해당 Step에 상태와 측정값을 기록한다. 두 HTML 파일은 발표 자료와 UI 목업(번들 형식, 7탭 화면 설계 원본)이다.

## 명령어

백엔드 명령은 모두 `shortforge/backend`에서 `uv`로 실행한다 (Python 3.11, `.venv`는 uv가 관리).

```bash
uv sync                                   # 의존성 설치
uv run pytest -q                          # 전체 테스트
uv run pytest tests/test_orchestrator.py::test_rerun_marks_downstream_stale -q   # 단일 테스트
uv run ruff check . && uv run ruff format --check .
uv run python ../scripts/render_spike.py [--images DIR] [--presets veryfast,medium] [--no-bgm]
                                          # 실제 S5→S7 경로 렌더 벤치마크 (LLM·YouTube만 Fake)
python ../scripts/doctor.py [--offline]   # 환경 점검: FFmpeg 필터, venv, .env 키 실검증, Edge-TTS
```

- 설정은 `shortforge/.env`(템플릿 `.env.example`)에서 `app/config.py`의 `Settings`로 읽는다. 엔진 전환은 `LLM_MODE`, `IMAGE_MODE`, `TTS_MODE`, `RENDER_PRESET` 등 설정값만으로 한다.
- FFmpeg는 winget으로 설치되어 PATH에 없을 수 있다. 코드는 `app/media.find_exe()`로 찾는다(PATH → `%LOCALAPPDATA%\Microsoft\WinGet\Links`).
- `test_render.py`는 실제 FFmpeg로 작은 캔버스(270×480)를 렌더하며, FFmpeg가 없으면 건너뛴다.
- 런타임 데이터는 `shortforge/data/`에 쌓이고 git에서 제외된다.

## 아키텍처

### Project JSON이 유일한 단계 간 통로
`app/schemas/project.py`의 `Project`가 단일 진실 원천이다. 각 단계는 **선언한 키만 읽고 출력 키 하나만 쓴다**. 단계끼리 직접 import하거나 호출하지 않는다.

| 단계 | 읽기 | 쓰기 |
|---|---|---|
| s1 입력 | (자기 출력 `input`을 `ctx.current()`로) | `input` |
| s2 탐색 | `input` | `refs` |
| s3 요인 | `input`, `refs` | `factors` |
| s4 전략 | `input`, `factors` | `strategy` |
| s5 자산 | `input`(user_media), `strategy` | `assets` |
| s6 타임라인 | `strategy`, `assets` | `timeline` |
| s7 렌더 | `timeline` | `render` |

이 표의 기준 구현은 `app/orchestrator.py`의 `_build_pipeline()`이다. 단계 함수는 `async def run(ctx: StepContext) -> <출력>` 형태이고, 반환값을 오케스트레이터가 스키마로 검증해 기록한다. `ctx.read(key)`는 선언하지 않은 키를 읽으면 `ContractViolation`을 낸다. `ctx.warn()`의 내용은 `project.warnings[step]`에 남고, `StepInputError` 메시지는 사용자에게 그대로 보인다.

### 오케스트레이터 규칙 (`app/orchestrator.py`)
- 상태: `idle | running | done | stale | error`. 단계는 읽는 키를 쓰는 앞 단계가 모두 `done`일 때만 실행할 수 있다(아니면 `StepBlocked`).
- **Stale 전파:** 단계 출력이 바뀌면(실행 성공이든 `edit()`를 통한 사용자 편집이든) 뒤 단계는 출력이 있으면 `stale`, 없으면 `idle`이 된다. 자동 재실행은 하지 않는다.
- 단계 예외는 `status=error` + `errors[step]`로 기록하고 이전 출력은 보존한다. `run_all`은 첫 오류에서 멈춘다.
- 프로젝트별 `asyncio.Lock`으로 동시 실행·편집을 막는다(`ProjectBusy`). 진행 이벤트는 `EventBus`로 발행된다(SSE용).
- 저장(`app/store.py`): `data/projects/{id}/project.json`을 임시 파일 교체로 원자적 저장하고, 버전은 `versions/v{n}.json`, 목록은 SQLite에 둔다. `running` 같은 일시 상태는 `snapshot=False`로 저장한다. Windows에서는 백신·인덱서 잠금 때문에 교체가 `PermissionError`를 낼 수 있어 재시도 로직이 있다. 이 로직을 제거하면 테스트가 간헐적으로 깨진다.

### 어댑터 (`app/adapters/`)
모든 외부 모델·API는 `base.py`의 추상 클래스(`LLMAdapter`, `YouTubeAdapter`, `TTSAdapter`, `ImageAdapter`, `VideoAdapter`) 뒤에 둔다. 조립은 `registry.build_adapters()`가 맡는다.
- `fake.py`: 결정론적 Fake. 테스트와 오프라인 개발에 쓴다. `FakeLLM`은 `task` 이름(`s1_keywords`, `s3_factors`, `s4_strategy`)별 `_<task>` 메서드로 응답한다. LLM 호출을 추가하면 여기에도 응답을 추가해야 한다.
- 실제 구현: `tts/edge.py`(mp3 + `*.words.json` 어절 타이밍), `video/ffmpeg.py`, `image/upload.py`(생성하지 않음). YouTube(Step 3)와 LLM(Gemini/Ollama, Step 4)은 아직 없다. `build_adapters(settings, fake_missing=True)`는 없는 어댑터를 Fake로 채운다.

### 렌더 파이프라인 (`app/adapters/video/ffmpeg.py`, `app/subtitles.py`)
- 장면 k의 시작 시각은 `S_k = Σ d_j`(j<k, `d` = 음성 + pad)이다. 전환 길이 `T_k`만큼 클립 k를 앞으로 늘리고, xfade offset은 `S_k − T_k`, 음성은 `adelay`로 정확히 `S_k`에 놓는다. 총 길이는 `Σd`이다. 타이밍을 고칠 때는 이 불변식을 유지한다.
- 장면 클립은 병렬(`workers` = 코어 수의 절반)로 zoompan 인코딩하고, 합성은 filter_complex 하나로 처리한다(`render/work/graph.txt`에 저장됨). ffmpeg는 `cwd=project_dir`로 실행해서 `ass=` 필터에 상대 경로를 쓴다(Windows 경로 이스케이프를 피하기 위함).
- 자막은 Whisper가 아니라 TTS 어절 타이밍으로 만든다. Edge-TTS 7.x는 `boundary="WordBoundary"`를 명시해야 한다. 타이밍에 문장부호가 없으므로 원문 대사(`caption.text`)에서 쉼표·마침표 위치를 찾아 끊는다. 침묵 구간은 강제 구분으로, 그 너머로 자막을 합치지 않는다.

### LLM 프롬프트
`app/prompts/sN_*.md`의 첫 줄은 반드시 `version: x.y`여야 한다(`app/llm.load_prompt`가 검사함). 레퍼런스 제목·댓글 같은 외부 텍스트는 `wrap_untrusted()`로 감싼다. S3는 선택된 영상을 가리키지 않는 evidence를 지우고, 근거가 없어진 요인은 버린다. `hook`/`visual` 요인은 항상 `estimated`로 둔다.

## 절대 제약 (`PROJECT_PROMPT.md` §2, §12)
- 과금 API·SDK(OpenAI, Anthropic, ElevenLabs, Replicate, Runway, Vertex 등)를 쓰지 않는다. `tests/test_cost_guard.py`가 import와 `pyproject.toml` 의존성 허용 목록을 검사한다. 새 의존성은 허용 목록에 추가하고 이유를 남긴다.
- YouTube: `search.list`(100 units) 전에 캐시를 확인한다. 통계는 `videos.list`/`channels.list`로 50개씩 일괄 조회한다. 일 8,000 units를 넘으면 차단한다. API 키를 여러 개 돌려 쓰는 로직은 금지다.
- 레퍼런스 영상·이미지·음성은 다운로드하지 않는다(yt-dlp 금지). 메타데이터, 통계, 공개 댓글, 썸네일 URL만 쓴다.

## 개발 환경 메모
개발 PC는 GPU가 없고(Intel UHD 620) RAM이 8GB이며 CPU는 i5-8265U다. 그래서 기본 경로는 "업로드 사진 + Edge-TTS + Gemini 무료 등급"이다(D3, D4). ComfyUI/FLUX/Wan을 로컬에서 실행하는 것은 전제하지 않는다. 문서와 사용자 커뮤니케이션은 한국어로 한다.
