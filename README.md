# ShortForge

잘 된 숏폼의 구조를, 내 이야기로. 주제를 입력하면 YouTube 레퍼런스 분석 → 성공 요인 → 장면 전략 → 자산 → 합성 지시서 → 렌더까지 7단계로 30초 세로 영상(MP4 + SRT)을 만든다. **비용 ₩0**(무료 쿼터 + 로컬 오픈소스), GPU 없이 동작한다.

- 사용자: [`docs/BETA_GUIDE.md`](docs/BETA_GUIDE.md) — `shortforge/setup.bat` → `.env`에 키 2개 → `shortforge/start.bat`
- 개발자: [`CLAUDE.md`](CLAUDE.md) (명령어·아키텍처), [`PROJECT_PLAN.md`](PROJECT_PLAN.md) (Step별 상태)
- 기획: [`PRD.md`](PRD.md), [`PROJECT_PROMPT.md`](PROJECT_PROMPT.md), [`docs/DECISIONS.md`](docs/DECISIONS.md), [`docs/DOD_M1.md`](docs/DOD_M1.md)

| 구성 | 기술 |
|---|---|
| 백엔드 | Python 3.11, FastAPI, Pydantic v2, SQLite (`shortforge/backend`) |
| 웹 UI | Next.js 16, Tailwind v4 (`shortforge/frontend`) |
| LLM | Gemini 무료 등급 / Ollama |
| 데이터 | YouTube Data API v3 (메타데이터·통계·댓글만, 미디어 다운로드 없음) |
| 음성·자막 | Edge-TTS, TTS 어절 타이밍 자막 |
| 렌더 | FFmpeg (CPU, 30초 영상 약 50초) |
