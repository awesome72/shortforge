# ShortForge

잘 된 숏폼의 구조를, 내 이야기로. 주제를 입력하면 YouTube 레퍼런스 분석 → 성공 요인 → 장면 전략 → 자산 → 합성 지시서 → 렌더까지 7단계로 30초 세로 영상(MP4 + SRT)을 만든다. **비용 ₩0**(무료 쿼터 + 로컬 오픈소스), GPU 없이 동작한다.

현재 버전: **v0.3.0-beta.4** (사전 배포판, [릴리스](https://github.com/awesome72/shortforge/releases)) · 진행 상태는 [`PROJECT_PLAN.md`](PROJECT_PLAN.md), 변경 내역은 [`CHANGELOG.md`](CHANGELOG.md)

## 할 수 있는 일

| 단계 | 내용 |
|---|---|
| 1. 개인 입력 | 주제·타깃·톤·길이, 본인 사진 업로드 |
| 2. 레퍼런스 탐색 | 최근 90일 숏폼을 구독자 대비 조회수·좋아요율로 점수화, LLM 주제 관련성 판정 (1회 약 300 units) |
| 3. 성공 요인 | 메타데이터·댓글·썸네일(Gemini가 URL로 직접 봄)을 근거로 단 요인, "확인/추정" 표시 |
| 4. 제작 전략 | 장면 스토리보드, 제목 A/B, 대사 편집, 장면 드래그 재정렬 |
| 5. 자산 | 본인 사진 → Cloudflare 무료 AI 생성 → Pixabay 무료 사진, Edge-TTS 음성, 후보 3개 중 고르기 |
| 6. 합성 지시서 | 모션·전환·자막 스타일, 렌더 전 브라우저 미리보기 |
| 7. 렌더 | FFmpeg CPU 렌더(30초 영상 약 50초), MP4·SRT 다운로드, 업로드 전 AI 고지 체크리스트 |

그 밖에: A/B 변형 프로젝트 복제, 버전 기록·되돌리기, 앞 단계를 고치면 뒤 단계에 "재생성 필요" 표시, 무료 한도 소진 시 경량 모델·다른 이미지 소스로 자동 대체, 키가 빠지면 화면에서 안내, 선택형 고급 모드(본인 Anthropic·OpenAI·OpenRouter 키로 분석·전략만 유료 모델, 하루 예산 상한, 기본은 꺼짐).

## 문서

- 사용자: [`docs/BETA_GUIDE.md`](docs/BETA_GUIDE.md) — `shortforge/setup.bat` → `shortforge/start.bat` → 화면의 "설정"에서 키 2개. 피드백은 [`docs/BETA_FEEDBACK.md`](docs/BETA_FEEDBACK.md), 베타 운영(모집·배포·집계)은 [`docs/BETA_RECRUIT.md`](docs/BETA_RECRUIT.md)
- 개발자: [`CLAUDE.md`](CLAUDE.md) (명령어·아키텍처), [`PROJECT_PLAN.md`](PROJECT_PLAN.md) (Step별 상태와 측정값)
- 기획: [`PRD.md`](PRD.md), [`PROJECT_PROMPT.md`](PROJECT_PROMPT.md), [`docs/DECISIONS.md`](docs/DECISIONS.md) (D1~D12), [`docs/DOD_M1.md`](docs/DOD_M1.md)
- 소개 페이지(현재 상태 요약): [`docs/intro.html`](docs/intro.html) — claude.ai Artifact로도 게시(비공개, 공유는 페이지의 Share 메뉴)
- 발표 자료(초기 제안): `ShortForge 발표.html`, UI 목업: `ShortForge 숏폼 스튜디오.html`

## 구성

| 구성 | 기술 |
|---|---|
| 백엔드 | Python 3.11, FastAPI, Pydantic v2, SQLite (`shortforge/backend`) |
| 웹 UI | Next.js 16, Tailwind v4 (`shortforge/frontend`) |
| LLM | Gemini 무료 등급(작업별 모델 분리, 이미지 URL 입력) / Ollama |
| 데이터 | YouTube Data API v3 (메타데이터·통계·댓글·썸네일 URL만, 미디어 다운로드 없음) |
| 이미지 | 본인 사진, Cloudflare Workers AI(FLUX.2 klein, 하루 약 64장 무료), Pixabay |
| 음성·자막 | Edge-TTS, TTS 어절 타이밍 자막 |
| 렌더 | FFmpeg (CPU) |
