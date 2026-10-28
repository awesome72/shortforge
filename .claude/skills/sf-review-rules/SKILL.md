---
name: sf-review-rules
description: "ShortForge 변경을 검토할 때 쓰는 프로젝트 고유 규칙 점검표(단계 간 계약, 비용 ₩0, 공개 저장소 노출, 렌더 불변식, 버전 상수, 화면 문구, 테스트). 커밋 전 검토, 'sf-reviewer', '규칙 확인', '이 변경 괜찮아?' 요청에 사용한다. 일반적인 코드 스타일 검토에는 쓰지 않는다."
---

# ShortForge 검토 규칙

규칙마다 **왜 생겼는지**를 적었다. 예외가 보이면 이유에 비춰 판단한다. 근거 문서는 루트 `CLAUDE.md`와 `docs/DECISIONS.md`다.

## 1. 공개 저장소 노출 (치명)
- 스테이징에 `.env*`(`.env.example` 제외), `shortforge/data/`, `.next*`, `_workspace/`, `test-results/`가 없어야 한다. 저장소가 2026-10-21에 공개로 바뀌었다. 올라가면 되돌려도 노출이다.
- 코드·로그·문서에 키 값을 넣지 않는다. 로그는 `support.py`가 키를 `[숨김]`으로 지우는 경로를 거쳐야 한다.
- `frontend/tsconfig.json`에 `.next-dev`·`.next-verify`·`.next-e2e` 경로가 들어간 채 커밋하지 않는다(개발 서버가 자동으로 넣는다).

## 2. 비용 ₩0 (치명)
- 유료 SDK(anthropic, openai 등)는 `app/adapters/llm/advanced/` 안에서만 import한다. `tests/test_cost_guard.py`가 지킨다.
- 새 의존성은 `pyproject.toml` 허용 목록과 이유가 함께 있어야 한다.
- 무료 등급만: 체험 크레딧(무료 크레딧으로 시작하는 서비스)에 기대는 경로를 만들지 않는다.
- YouTube 레퍼런스 영상·이미지·음성을 내려받지 않는다(yt-dlp 금지). 무료 소스 영상(Pixabay 등, D15)은 약관이 허락한 별개다.

## 3. 단계 간 계약
- 단계는 `_build_pipeline()`에 선언한 키만 읽고 출력 키 하나만 쓴다. 읽는 키를 바꾸면 CLAUDE.md 표도 바꾼다.
- 스키마(`schemas/project.py`)를 바꾸면 프론트 `lib/types.ts`도 같은 모양으로 바꾼다.
- 새 LLM 작업은 `config.LLM_TASKS`, `FakeLLM._<task>`, (경량이면) `gemini.LIGHT_TASKS`, `prompts/<task>.md`(첫 줄 `version:`)가 함께 있어야 한다.
- 외부 텍스트(제목·댓글·태그·이미지 속 글자)는 `wrap_untrusted()`로 감싼다(프롬프트 주입 방어).

## 4. 버전 상수 (바꾸면 올린다)
| 상수 | 언제 올리나 | 안 올리면 |
| --- | --- | --- |
| `CLIP_VERSION` (ffmpeg.py) | 장면 클립 필터·인코딩 변경 | 옛 클립 캐시가 재사용된다 |
| `RENDER_QUALITY` (s7_render.py) | 결과가 눈에 띄게 달라지는 렌더 변경 | '새 방식으로 다시 렌더' 안내가 안 뜬다 |
| `PROMPT_REV` (image_prompt.py) | 이미지 프롬프트 규칙 변경 | 옛 생성 이미지가 재사용된다 |
| `MUSIC_VERSION` (music.py) | 합성 방식 변경 | 옛 곡 파일이 재사용된다 |
| `COVER_VERSION` (publish.py) | 커버 만드는 방식 변경 | 옛 커버가 그대로 보인다 |
| 프롬프트 `version:` | 프롬프트 내용 변경 | 기록으로 어떤 프롬프트였는지 모른다 |

## 5. 렌더·자막
- 타이밍 불변식: 장면 시작 `S_k = Σd`, 전환 길이만큼 클립을 앞으로 늘리고 음성은 `adelay`로 정확히 `S_k`. 클립 프레임 수는 올림 + 1(반올림하면 컷 전환에서 영상이 끊겼다).
- FFmpeg는 `media.run()`으로만(asyncio 서브프로세스는 Windows `--reload` 루프에서 깨진다).
- 합성 단계(filter_complex)에 RGB 필터를 넣지 않는다(30초 합성이 3배 느려졌다). 무거운 보정은 클립 단계.
- ASS 문자열의 역슬래시: 파이썬 스크립트로 파일을 고칠 때 `\N`, `\p1`이 한 단계씩 빠지기 쉽다. 결과 파일을 다시 읽어 확인한다.

## 6. 화면
- 색은 `globals.css` `@theme` 토큰만(직접 색 값 금지). 한글 문장에 `font-mono` 금지. 숫자는 `tabular-nums`.
- 단계 설명은 기술 용어 없는 해요체, 기술 설명은 `StepHeader`의 `tech`.
- 실행 엔드포인트는 `async def`(동기면 백그라운드 태스크를 못 만든다). 요청 본문 모델은 모듈 수준에 정의한다(`from __future__ import annotations` 때문에 함수 안 모델은 FastAPI가 못 찾는다).

## 7. 테스트
- 새 동작마다 테스트가 있어야 한다. 외부 API는 `httpx.MockTransport`(API 앱은 `app.state.*_transport`)로, 실제 키·쿼터를 쓰지 않는다.
- 개발자 `.env`에 기대는 테스트를 만들지 않는다(새 clone에서만 깨진다).
- 화면 흐름을 바꿨으면 `frontend/e2e/`도 맞춘다.
- 문서: 동작이 바뀌면 `CHANGELOG.md` "다음 버전", 구조가 바뀌면 `CLAUDE.md`, 실측·결정은 `docs/DECISIONS.md`.
