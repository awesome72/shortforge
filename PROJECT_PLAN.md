# ShortForge — 프로젝트 실행 계획 (Project Plan)

| 항목 | 내용 |
|---|---|
| 문서 버전 | v1.0 |
| 작성일 | 2026-10-15 |
| 기준 문서 | `PRD.md` v0.1, `PROJECT_PROMPT.md`, `ShortForge 발표.html`(12장), `ShortForge 숏폼 스튜디오.html`(7탭 목업) |
| 목적 | 기획 문서를 **실행 가능한 Step**으로 쪼개고, 각 Step의 산출물과 완료 조건(Gate)을 정한다 |

---

## 1. 자료 검토 요약

| 자료 | 성격 | 핵심 내용 | 계획에서의 역할 |
|---|---|---|---|
| `PRD.md` | 제품 요구사항 | 문제·목표·페르소나(P1 1인 크리에이터), 기능 ID(F-W*, F-1.1~F-7.4, P0/P1/P2), KPI, 리스크, M0~M3 | **무엇을·왜** (충돌 시 최우선) |
| `PROJECT_PROMPT.md` | 구현 지시서 | 절대 제약 6개, 스택, 디렉터리, Project JSON 계약, Timeline 스키마, 단계별 지침, API, DoD | **어떻게** (구현 기준) |
| `ShortForge 발표.html` | 기획 발표 12장 | 문제→솔루션→파이프라인→조율→스코어링→요인→무료 스택→리스크→KPI→로드맵→결정 | 이해관계자 설득용, 결정 2건 제안 포함 |
| `ShortForge 숏폼 스튜디오.html` | UI 목업 (1440×1180) | 상단 쿼터 미터·"전체 실행", 좌측 7단계 탭, 중앙 단계 화면, 우측 Project JSON 상태 + 단계별 무료 도구 패널 | 프론트엔드 화면 설계 원본 |

**한 줄 요약:** 기획·설계 문서는 충분히 성숙해 있다(스키마·API·DoD까지 정의). 지금 필요한 것은 *추가 기획*이 아니라 **가장 위험한 가정부터 코드로 검증하는 순서 설계**다.

---

## 2. 진단 — 강점, 빈틈, 현실 제약

### 2.1 강점 (그대로 유지)
- **Project JSON 단일 진실 원천 + 단계별 읽기/쓰기 키 계약** → 단계별 독립 개발·테스트가 가능하다.
- **어댑터 패턴** → 무료 정책 변경(Gemini 축소 이력)에 대한 내성이 설계에 들어가 있다.
- **confirmed / estimated + evidence 필수** → "사후 합리화" 리스크에 대한 구조적 방어.
- **DoD가 측정 가능**(쿼터 ≤400 units, CPU 렌더 ≤3분, stale 단위 테스트 등).

### 2.2 문서 간 빈틈·충돌 (Step 0에서 정리)

| # | 이슈 | 내용 | 제안 |
|---|---|---|---|
| G1 | **UI 이중 개발** | M0는 Streamlit, M1은 Next.js. 2주짜리 화면을 버리게 된다 | M0는 **CLI + Project JSON 파일**로 E2E를 검증하고, UI는 M1에서 목업 기반 Next.js로 한 번만 만든다 |
| G2 | **Shorts 길이 기준** | YouTube Shorts는 2024년 10월부터 최대 3분. `videoDuration=short`는 4분 미만. 지침의 `≤60초` 필터는 일부 Shorts를 제외한다 | MVP 출력은 15/30/60초이므로 `≤ max(60, duration_sec×2)` 정도로 **설정값화**하고 기본은 60초 유지 |
| G3 | **자막 생성 경로** | Whisper로 SRT를 만들도록 되어 있으나, 대사는 이미 텍스트로 알고 있다 | Edge-TTS의 **WordBoundary 이벤트로 SRT를 직접 생성**(정확·빠름). Whisper는 사용자 녹음 음성일 때만 사용 |
| G4 | **쿼터 수치 표기 불일치** | PRD "S2 1회 ≤400", 발표 "프로젝트당 약 300", KPI 기준 350 | 계산식 고정: search 3회(300) + videos/channels(~2) + commentThreads 4회(4) ≈ **306 units**. 문서 3곳 동일하게 정리 |
| G5 | **데이터 보관 기간** | Project JSON에 refs 통계를 장기 저장 | YouTube API 정책상 저장 데이터의 갱신/삭제 주기 확인 필요(보통 30일 기준). refs에 `fetched_at` 추가, 30일 경과 시 재조회/마스킹 |
| G6 | **DoD의 Docker 전제** | "`docker compose up` 1회" | 개발 PC에 Docker 미설치·RAM 8GB. 개발은 **네이티브(venv + npm)**, Docker는 M1 패키징 Step에서 별도 검증 |

### 2.3 개발 환경 현실 (2026-10-15 실측)

| 항목 | 상태 | 계획에 미치는 영향 |
|---|---|---|
| Python | 3.11.9 ✅ | 백엔드 바로 착수 가능 |
| Node | v24 ✅ | Next.js 가능 |
| Git | ✅ (폴더는 아직 repo 아님) | Step 0에서 `git init` |
| FFmpeg | ❌ 미설치 | Step 0에서 설치 (winget/gyan build) |
| Docker | ❌ 미설치 | 패키징 단계로 연기 |
| GPU | ❌ Intel UHD 620 (내장) | **ComfyUI/FLUX/SDXL/Wan 로컬 실행 불가** → 기본 경로는 "업로드 사진 + TTS" |
| RAM | 8GB | Ollama는 3B급 소형 모델만 현실적. 기본 LLM은 Gemini 무료 등급 |

> **결론:** 이 PC는 PRD 리스크 표의 "GPU 없는 사용자"(가능성 높음) 그 자체다. 그러므로 **GPU 없는 경로를 1급 시민(기본 경로)** 으로 설계하고, 이미지 생성은 어댑터 뒤의 선택 기능으로 둔다. 이 판단은 P1 페르소나(입문 크리에이터) 현실과도 맞는다.

---

## 3. 진행 전략 (원칙 5가지)

1. **얇은 E2E 먼저 (Walking Skeleton).** 7단계를 각각 완벽히 만들기보다, 품질이 낮더라도 입력→MP4가 한 번 끝까지 도는 것을 2주 안에 만든다.
2. **가장 위험한 것부터.** 위험도 순서: ① CPU 렌더 3분 ② YouTube 쿼터/데이터 품질 ③ LLM JSON 안정성 ④ UI. → 렌더 스파이크를 S2보다 먼저 한다.
3. **계약(Schema) 우선, 단계는 나중.** Pydantic 스키마와 오케스트레이터가 먼저 있으면 각 단계는 "읽고 하나 쓰는 함수"로 병렬 개발된다.
4. **고정 Fixture로 개발.** 한 번 받은 YouTube 응답·LLM 응답을 `tests/fixtures/`에 저장하고 재사용 → 쿼터와 무료 RPD를 개발에 낭비하지 않는다.
5. **모든 Step은 Gate로 끝난다.** Gate를 통과하지 못하면 다음 Step으로 가지 않고 범위를 줄인다.

---

## 4. 단계별 실행 계획 (Steps)

전체 흐름:

```
Step0 준비 → Step1 계약/오케스트레이터 → Step2 렌더 스파이크 → Step3 S2 YouTube
   → Step4 LLM 단계(S1/S3/S4) → Step5 S5/S6 연결 = ★M0 E2E
   → Step6 웹 UI 7탭 → Step7 품질(자막·오디오·TTS) → Step8 이미지 생성(선택) → Step9 패키징/베타 = ★M1
   → Step10 고도화 = ★M2 → Step11 확장 = M3
```

---

### Step 0 — 준비 & 결정 (2일 · 10/15–10/16)

**목표:** 코드를 쓰기 전에 환경·키·결정을 확정한다.

| 작업 | 상세 |
|---|---|
| 0-1 저장소 | `git init`, `shortforge/` 디렉터리 골격(`PROJECT_PROMPT.md` §4), `.gitignore`(data/, .env), `.env.example` |
| 0-2 도구 설치 | FFmpeg, `uv`(또는 venv), `edge-tts`, `ruff`/`pytest` |
| 0-3 키 발급 | Google Cloud 프로젝트 → YouTube Data API v3 키, Google AI Studio → Gemini 키 |
| 0-4 결정 확정 | §6 결정 사항 D1~D4 확정 (권장안 채택 여부) |
| 0-5 문서 정합성 | §2.2 G1~G6 반영해 PRD/PROMPT 수정 (v0.2) |

**산출물:** 빈 repo + 설치 확인 스크립트(`scripts/doctor.py`: ffmpeg/키/모델 상태 출력)
**Gate:** `python scripts/doctor.py` 전 항목 OK, 결정 D1~D4 기록 완료

> **상태 (2026-10-15): 완료.** `python scripts/doctor.py` 전 항목 통과 (YouTube·Gemini 키 유효, `gemini-2.5-flash` 사용 가능). Ollama는 선택 항목이라 WARN.

---

### Step 1 — 계약 & 오케스트레이터 (3일 · 10/17–10/21)

**목표:** Project JSON 스키마와 단계 실행/stale 전파 엔진. (지시서 Milestone 1)

| 작업 | 상세 | 관련 요구사항 |
|---|---|---|
| 1-1 스키마 | `schemas/project.py`: Input, Ref, Factor, Strategy/Scene, Asset, Timeline, Render (Pydantic v2) + JSON Schema export | F-6.1 |
| 1-2 저장소 | SQLModel(SQLite) 메타 + `data/projects/{id}/project.json` 버전 증가 저장 | F-W5 기반 |
| 1-3 오케스트레이터 | `run_step(n)`, `run_all(from=n)`, 단계 레지스트리(읽기/쓰기 키 선언), 상태 머신 idle→running→done/error | F-W4 |
| 1-4 stale 전파 | 키 변경 시 뒤 단계 `stale`, 자동 재실행 없음 | F-W3 |
| 1-5 어댑터 인터페이스 | `LLMAdapter`, `TTSAdapter`, `ImageAdapter`, `VideoAdapter`, `YouTubeAdapter` 추상 클래스 + **Fake 구현** | 제약 2 |
| 1-6 비용 가드 | 어댑터 화이트리스트 검사 테스트(유료 SDK import 시 실패) | NFR 비용 |

**Gate:** Fake 어댑터만으로 `run_all` 7단계 통과, stale 단위 테스트 통과, 화이트리스트 테스트 통과

> **상태 (2026-10-15): 완료.** 테스트 30개 통과(25회 반복 실행 시 실패 0건), ruff 통과.
> - 추가 결정: 뒤 단계는 출력이 있을 때만 `stale`, 없으면 `idle`. S5는 `user_media` 때문에 `input`도 읽는다. 진행 중(running) 상태는 버전 스냅샷을 남기지 않는다.
> - 발견한 문제: Windows에서 백신·인덱서가 파일을 잡고 있으면 `project.json` 교체가 간헐적으로 `PermissionError`로 실패했다. 재시도 로직을 넣어 고쳤다.
> - S2~S6에는 최소 로직만 미리 넣었다: 점수 공식, 근거 필터, hook 검사, 규칙 기반 타임라인. 캐시·쿼터는 Step 3, LLM 재시도와 유사도 검사는 Step 4, LLM 타임라인은 Step 5에서 붙인다.

---

### Step 2 — 렌더 스파이크 (S7 선행) (3일 · 10/22–10/24)

**목표:** 최대 기술 리스크인 **"CPU만으로 30초 영상 ≤3분"** 을 이 노트북에서 먼저 증명한다. (지시서 Milestone 4를 앞당김)

| 작업 | 상세 |
|---|---|
| 2-1 손으로 쓴 Timeline | 사진 5장 + 대사 5줄로 `timeline.json` 수기 작성 |
| 2-2 TTS | `EdgeTTSAdapter`: 장면별 wav + WordBoundary 타이밍 수집 |
| 2-3 장면 클립 | 이미지 사전 리사이즈(1080×1920 crop) → `zoompan` → 클립. 프리셋 비교(`veryfast` vs `medium`) |
| 2-4 합성 | concat(+fade/xfade) → BGM `sidechaincompress` 덕킹 → ASS 자막 번인 → H.264 CRF 20 / AAC 192k |
| 2-5 SRT | WordBoundary 기반 SRT 생성(줄당 14자) |
| 2-6 계측 | 단계별 소요 시간 로그 → `render.log` |

**Gate:** 30초 MP4 + SRT 생성, **총 렌더 ≤3분** (실패 시 대안: 720×1280 렌더 후 업스케일, zoompan 대신 `scale+crop` 표현식, 클립 병렬 처리)

> **상태 (2026-10-15): 통과.** 기준 장비 i5-8265U(4코어, 저전력), RAM 8GB, GPU 없음.
>
> | 항목 | 측정값 |
> |---|---|
> | S5 Edge-TTS 5장면 | 4.5~7.4초 |
> | S7 렌더 (veryfast) | 34.1~46.8초 (클립 13~17초 + 합성 21~30초) |
> | **합계** | **41.5~51.3초 / 목표 180초** |
> | S7 렌더 (medium) | 146.6초 → 여유가 없어 기본값은 veryfast로 확정 |
> | 산출물 | H.264 1080×1920 30fps, AAC 48kHz, 29.0초, 8.3MB, SRT |
> | 음량 | -17.7 LUFS (Shorts 권장 -14) → Step 7에서 정규화 |
>
> - 자막은 Edge-TTS 어절 타이밍(`boundary="WordBoundary"`, edge-tts 7.x부터 명시 필요)으로 만든다. 원문 대사의 쉼표·마침표에서 우선 끊고, 긴 구절은 글자 수를 고르게 나누며, 3자 이하 고아 자막을 막는다.
> - 남은 확인: zoompan 모션의 미세한 떨림(jitter)은 영상을 직접 봐야 판단할 수 있다. 떨림이 보이면 `supersample`(기본 1.5배)을 올린다.
> - 재현: `cd shortforge/backend && uv run python ../scripts/render_spike.py [--images 사진폴더] [--presets veryfast,medium]`

---

### Step 3 — S2 레퍼런스 탐색 (3일 · 10/24–10/28)

**목표:** 구독자 대비 상위 숏폼 10개를 쿼터 안에서 안정적으로. (지시서 Milestone 2)

| 작업 | 상세 | 요구사항 |
|---|---|---|
| 3-1 YouTubeAdapter | `search.list` → `videos.list`(50개 일괄) → `channels.list`(일괄) | F-2.1 |
| 3-2 지표·스코어 | ratio(`max(subs,100)`), vpd, like_rate, z-score 가중합, 숨김 구독자 → ratio null 처리 | F-2.2 |
| 3-3 캐시 | 키 `(keyword, region, lang, date)`, TTL 24h, SQLite | F-2.4 |
| 3-4 쿼터 미터 | 호출별 units 기록, 일 8,000 초과 시 차단, `GET /quota` | F-2.4, 제약 4 |
| 3-5 Fixture | 실제 응답 1회 저장 → 이후 테스트는 Fixture 사용 | – |

**Gate:** 키워드 3개 1회 실행 ≤400 units(테스트로 검증), 같은 입력 재실행 시 0 units(캐시 히트)

> **상태 (2026-10-15): 통과.** 가짜 YouTube 서버 테스트와 실제 API 스모크 모두 통과.
>
> | 실측 (실제 API) | units |
> |---|---|
> | S2 1회차 (search 3 + videos 2 + channels 1) | **303** |
> | S2 같은 날 재실행 | **0** |
> | S3 댓글 (선택 4개) | 4 |
>
> - 쿼터·캐시 날짜는 **태평양 시간(PT)** 기준이다(YouTube 쿼터가 PT 자정에 초기화). Windows용으로 `tzdata` 의존성을 추가했다.
> - search 외의 조회(videos/channels/commentThreads)도 항목 단위로 24시간 캐시한다. 그래야 재실행이 0 units가 된다.
> - 3-5 Fixture: 실제 응답(타인의 제목·댓글)을 저장소에 커밋하지 않으려고, 가짜 YouTube 서버(`httpx.MockTransport`)로 대체했다.
> - **미결 (Step 4에서 결정):** `order=viewCount` 검색은 키워드와 느슨하게만 맞는 인기 영상을 섞는다. 실측 예로 "퇴근 후 홈트" 검색에 어깨 운동 영상이 2위로 나왔다. 점수 공식에는 주제 관련성 항이 없다. 후보 해법: (a) `order=relevance`로 검색한 뒤 점수로 정렬, (b) S3 앞에 LLM 관련성 필터(쿼터 0), (c) 지금처럼 사용자가 선택을 해제.
> - 재현: `cd shortforge/backend && uv run python ../scripts/youtube_smoke.py [--keywords "a,b,c"] [--with-comments]`

---

### Step 4 — LLM 단계: S1 · S3 · S4 (4일 · 10/27–10/30)

**목표:** 키워드 생성 → 근거 있는 성공 요인 → 장면 스토리보드. (지시서 Milestone 3)

| 작업 | 상세 | 요구사항 |
|---|---|---|
| 4-1 LLM 어댑터 | `GeminiAdapter`(`response_schema`), `OllamaAdapter`(`format=json` + 검증, 3B급 모델로 스모크 테스트만) | 제약 2, 6 |
| 4-2 프롬프트 파일 | `prompts/s1_keywords.md`, `s3_factors.md`, `s4_strategy.md` (상단 `version:`) | §9 |
| 4-3 S1 | 입력 정규화 + 키워드 3~5개 | F-1.1, F-1.2 |
| 4-4 S3 | 메타데이터 + `commentThreads`(관련도순 100) → factors. 외부 텍스트는 `<untrusted>`로 감싸기. **evidence 없는 factor 폐기**, 메타데이터 직접 확인 항목만 confirmed | F-3.1, F-3.2 |
| 4-5 S4 | 장면 5~7개, 0~2초 hook 필수, 장면당 2~8초, `factor_refs`, 제목 A/B, 제목 토큰 Jaccard >0.6이면 재생성 | F-4.1, F-4.2 |
| 4-6 검증·재시도 | Pydantic 실패 → 오류 메시지 포함 최대 2회 재시도 → 실패 원인 표시 | DoD |

**Gate:** Fixture refs 4개로 S3 실행 시 evidence 커버리지 100%, S4 장면 길이 합 = 목표 ±15%, 프롬프트 인젝션 테스트(댓글에 "이전 지시 무시" 삽입) 통과

> **상태 (2026-10-15): 코드 완료, 실제 LLM 검증 대기 (키 문제).**
> - 구현: Gemini·Ollama 어댑터. 공통으로 JSON 스키마를 강제하고, 검증에 실패하면 오류를 넣어 2회 재시도한다. 429는 10/25/60초를 기다렸다 재시도한다.
> - S2 관련성 필터(D6). S3 근거 필드는 프롬프트에 실제로 넣은 필드만 인정한다(시청 지속률 등은 거부). S4는 훅·제목 유사도·길이를 검토하고, 문제가 있으면 [수정 요청]을 넣어 최대 3회 생성한다.
> - 테스트 84개 통과. Gate 3개 중 근거 커버리지 100%, 인젝션 태그 위조 방어, S4 길이·훅 재생성 규칙은 단위 테스트로 검증했다.
> - **막힘:** `gemini-2.5-flash`는 신규 사용자에게 404, 현재 키의 프로젝트는 선결제 결제가 연결되어 402(크레딧 소진). 결제가 연결된 프로젝트는 유료 등급이라 D7에 따라 쓰지 않는다. **결제가 없는 프로젝트의 키로 교체한 뒤** 다음을 실행해 실제 Gate를 닫는다:
>   `python scripts/doctor.py --probe-llm` → `cd backend && uv run python ../scripts/llm_smoke.py --inject`

---

### Step 5 — S5 · S6 연결 → ★M0 E2E 완성 (2일 · 10/30–10/31)

**목표:** 사용자 입력 1줄에서 MP4까지 **CLI로** 1편 생성. (지시서 Milestone 5)

| 작업 | 상세 | 요구사항 |
|---|---|---|
| 5-1 S5 | 장면별 이미지 프롬프트(+style_seed, negative, seed) — 이미지 생성은 **`UserUploadAdapter` 기본**, 프롬프트는 저장만. TTS 대본 다듬기(숫자 한글화, 쉼표 호흡) | F-5.1, F-5.2 |
| 5-2 S6 | Timeline 생성 → JSON Schema 검증 → 2회 재시도 → **규칙 기반 기본 타임라인** 폴백. `duration=auto` = 실제 wav 길이 + pad | F-6.1 |
| 5-3 CLI | `sf new "주제" --audience ... --duration 30`, `sf run --from 4`, `sf status` | F-W4 |
| 5-4 시나리오 테스트 | PRD §5 시나리오(퇴근 후 10분 홈트)로 1편 생성 | – |

**★ M0 Gate (2026-10-31):** PRD 시나리오로 MP4+SRT 생성, S2 편집 시 S3~S7 stale, `run --from 4` 부분 재실행 동작

> **상태 (2026-10-15): 구조 Gate 통과, 실제 LLM 확인만 남음 (Step 4와 같은 키 문제).**
> - CLI(`python -m app.cli`): new / run(--from, --step) / status / refs / show / select / set-line / set-photo / list. PRD 시나리오 3·5·6의 편집과 "재생성 필요" 전파를 테스트로 검증했다.
> - 실제 E2E (LLM만 Fake, YouTube·Edge-TTS·FFmpeg 실제): 입력부터 MP4+SRT까지 **21초**, YouTube 1 unit(캐시).
> - S5: TTS 대본 정리(이모지·해시태그·괄호 지문·물결 제거, 끝 문장부호). 사진이 장면보다 적으면 순환해 쓴다. **숫자 한글화는 하지 않는다** — 자막이 TTS 어절에서 나오므로 "10분"이 "십 분"으로 표시되기 때문이다. Edge-TTS의 숫자 읽기는 Step 7 블라인드 테스트에서 귀로 확인한다.
> - S6: 규칙 기반 타임라인(경로·길이 결정) 위에 LLM이 장면 연출(모션·전환·자막 스타일)만 고른다. LLM이 실패하면 규칙 기반을 쓴다. `S6_USE_LLM=false`면 LLM을 부르지 않는다.
> - **발견한 빈틈 → Step 7:** S4가 계획한 장면 시간과 TTS 실제 길이가 어긋나도 지금은 경고뿐이다(Fake 대사로 17.5초/30초). 목표 ±15%를 벗어나면 TTS rate를 자동으로 조정해 다시 합성하는 보정을 7-6으로 추가한다.

---

### Step 6 — 웹 UI 7탭 (8일 · 11/02–11/11)

**목표:** 목업(`ShortForge 숏폼 스튜디오.html`)을 실제 화면으로. (지시서 Milestone 7, 순서를 앞당김)

| 작업 | 상세 | 요구사항 |
|---|---|---|
| 6-1 FastAPI | §8 엔드포인트 8개, `PATCH` 시 stale 전파, `GET /events` SSE | F-W*, F-7.2 |
| 6-2 레이아웃 | 상단 바(프로젝트명·자동 저장·쿼터 미터·전체 실행), 좌측 7탭(상태 배지 5종), 우측 Project JSON 패널 + 단계별 무료 도구/한도/주의 | F-W1, F-W2 |
| 6-3 탭 화면 | S1 폼·업로드·키워드 칩 / S2 표+선택 / S3 요인 카드(근거·신뢰도) / S4 장면 카드+제목 A/B / S5 장면별 프롬프트·TTS / S6 엔진 선택+spec 뷰 / S7 진행률·미리보기·다운로드·"A/B 버전 만들기" | F-1~F-7 |
| 6-4 고지 | 무료 LLM 데이터 정책 고지 배너, 로컬 모드 토글 | 제약 6 |

**Gate:** 브라우저에서 PRD 시나리오 1~8번을 끝까지 수행 (`/qa`로 점검)

---

### Step 7 — 결과물 품질 (5일 · 11/12–11/18)

| 작업 | 상세 |
|---|---|
| 7-1 자막 스타일 | ASS 스타일 3종(hook_bold / body / emphasis), 안전 영역(상하 UI 가림) 반영 |
| 7-2 오디오 | BGM 라이브러리(무료 라이선스 확인된 곡 3~5개), 덕킹 수치 튜닝, 라우드니스 정규화(-14 LUFS) |
| 7-3 TTS 비교 | Edge-TTS vs MeloTTS 한국어 **블라인드 테스트**(PRD 미결 3), MeloTTS CPU 속도 측정 |
| 7-4 사용자 녹음 | 사용자 음성 업로드 시 faster-whisper(small, CPU)로 SRT |
| 7-5 장면 재생성 | 장면 단위 TTS/이미지 교체 (F-5.4 일부) |
| 7-6 길이 보정 | 음성 합계가 목표 ±15%를 벗어나면 TTS rate를 자동 조정해 다시 합성 (Step 5에서 발견) |

**Gate:** 내부 평가자 3명 기준 "업로드 가능한 수준" 3/3, TTS 엔진 결정 기록

---

### Step 8 — 이미지 생성 경로 (선택, 3일 · 11/19–11/23)

**목표:** GPU가 없는 환경을 전제로, 이미지 생성을 **선택 어댑터**로 붙인다.

| 옵션 | 내용 | 비용 원칙 |
|---|---|---|
| A. ComfyUIAdapter (원격 URL) | GPU가 있는 다른 PC/서버의 ComfyUI API에 연결(FLUX.1 schnell) | ₩0 유지 (본인 장비) |
| B. 생성 없음 + 스톡 대체 | 무료 라이선스 스톡 사진 검색 어댑터 | ₩0, 라이선스 표기 필요 |
| C. 프롬프트만 내보내기 | 사용자가 외부에서 생성 후 업로드 | ₩0, 가장 단순 |

**권장:** M1은 **C를 기본, A를 선택**으로 구현. CPU에서 SDXL/FLUX 실행은 시도하지 않는다.
**Gate:** `IMAGE_MODE=upload|comfyui` 설정만으로 전환됨

---

### Step 9 — 패키징 · DoD · 베타 (★M1, 11/24–11/30)

| 작업 | 상세 |
|---|---|
| 9-1 실행 패키징 | D1 결정(로컬 설치형) 기준: Windows용 원클릭 실행 스크립트 + (가능하면) `docker compose` 검증 |
| 9-2 DoD 점검 | `PROJECT_PROMPT.md` §10 7개 항목 체크 (Docker 항목은 G6 결정에 따름) |
| 9-3 보안 리뷰 | `/cso`: 프롬프트 인젝션, 업로드 파일 검증, 경로 탐색(`/files/{path}`) |
| 9-4 계측 | KPI 이벤트 로깅(완주율, 제작 시간, 재생성 비율, 근거 커버리지, 프로젝트당 units) — 로컬 파일 기반 |
| 9-5 베타 | P1 페르소나 10명 모집, 온보딩 가이드, 피드백 양식 |

**★ M1 Gate (2026-11-30):** DoD 통과, 베타 10명 각 1편 이상 완주

---

### Step 10 — 고도화 (★M2, 6주 · 12/01–2027-01-11)

| 기능 | 요구사항 |
|---|---|
| A/B 변형 프로젝트 복제 | F-W6 |
| 버전 히스토리 · 되돌리기 | F-W5 |
| 썸네일 비전 분석 (Gemini 멀티모달) | F-3.3 |
| 장면 드래그 재정렬 · 인라인 편집 | F-4.3 |
| 후보 3개 중 선택 | F-5.4 |
| 미리보기 플레이어 | F-7.4 |
| 스코어 가중치 보정 | 베타 사용자의 레퍼런스 선택으로 역추정 (PRD 미결 4) |
| AI 고지 체크리스트 | 업로드 전 안내 |

**Gate:** 베타 완주율 ≥40%(기준 시나리오), 1편 제작 시간 중앙값 ≤15분

### Step 11 — 확장 (M3, 2027-01 이후)
Remotion/Wan 어댑터, 업로드 성과 피드백 루프(본인 채널 OAuth Analytics), 팀 기능 → **사업화 판단**(유료 플랜 가치, 상업 이용 가능 스택 전환: Ollama + MeloTTS).

---

## 5. 일정 요약

| 기간 | Step | 마일스톤 |
|---|---|---|
| 10/15–10/16 | 0 준비·결정 | |
| 10/17–10/21 | 1 계약·오케스트레이터 | |
| 10/22–10/24 | 2 렌더 스파이크 | 렌더 3분 검증 |
| 10/24–10/28 | 3 S2 YouTube | |
| 10/27–10/30 | 4 LLM 단계 | |
| 10/30–10/31 | 5 S5/S6 → E2E | **★ M0 (10/31)** |
| 11/02–11/11 | 6 웹 UI | |
| 11/12–11/18 | 7 품질 | |
| 11/19–11/23 | 8 이미지(선택) | |
| 11/24–11/30 | 9 패키징·베타 | **★ M1 (11/30)** |
| 12/01–01/11 | 10 고도화 | **★ M2 (2027-01-11)** |

> 1인 개발·주 5일 기준 추정치. Step 3과 4는 Fixture 덕분에 일부 병행 가능.

---

## 6. 결정 필요 사항 (Step 0에서 확정)

| ID | 결정 | 선택지 | 권장안 | 근거 |
|---|---|---|---|---|
| D1 | 배포 형태 (PRD 미결 1) | 로컬 설치형 / 호스팅형 | **로컬 설치형** | ₩0 원칙 유지, 발표 자료 제안과 일치 |
| D2 | M0 UI | Streamlit / CLI / Next.js | **CLI (UI는 M1에서 Next.js 1회)** | 이중 개발 방지(G1) |
| D3 | 기본 LLM | Gemini 무료 / Ollama | **Gemini 기본 + Ollama 스모크 테스트 유지** | RAM 8GB에서는 소형 모델만 가능, 한국어 품질 |
| D4 | 기본 이미지 경로 | 생성 / 업로드 | **업로드 + 프롬프트 내보내기 기본**, ComfyUI 원격은 선택 | GPU 없음, PRD 리스크 대응과 일치 |
| D5 | 유료 플랜 가치 (PRD 미결 2) | 쿼터 / 고품질 엔진 / 성과 피드백 | M2 베타 데이터로 결정 | 발표 자료 제안과 일치 |

---

## 7. 검증 · 테스트 전략

| 층위 | 대상 | 방법 |
|---|---|---|
| 단위 | 스코어 공식, stale 전파, 쿼터 카운터, Jaccard, Timeline 길이 계산 | pytest, 외부 호출 없음 |
| 계약 | 각 단계 출력 Pydantic/JSON Schema | Fixture 입력 → 스키마 통과 |
| 어댑터 | YouTube/Gemini/Edge-TTS | 녹화된 응답(Fixture) + 주 1회 실제 호출 스모크 |
| 보안 | `<untrusted>` 인젝션, 업로드 파일, 경로 탐색 | 악성 댓글 Fixture, `/cso` |
| 성능 | CPU 렌더 시간, S2 units | 벤치마크 스크립트, CI 기록 |
| E2E | PRD §5 시나리오 | CLI(M0) → 브라우저 `/qa`(M1) |
| 비용 | 유료 경로 0개 | 어댑터 화이트리스트 테스트 |

---

## 8. 리스크 — 이 계획에서 추가·조정된 항목

| 리스크 | 가능성 | 조기 신호 | 대응 Step |
|---|---|---|---|
| CPU 렌더 3분 초과 (개발 노트북 i-series + 8GB) | 중간 | Step 2 계측 | Step 2 대안(해상도·필터 교체·병렬) |
| Gemini 무료 RPM/RPD로 개발 중단 | 중간 | 429 응답 | Fixture 재사용, 응답 캐시, Ollama 폴백 |
| 소형 LLM의 JSON 품질 저하 | 높음 | 스키마 실패율 | 재시도 2회 + 규칙 기반 폴백(S6), 프롬프트 단순화 |
| Edge-TTS 비공식 엔드포인트 차단 | 중간 | TTS 실패 | MeloTTS 어댑터 Step 7에서 준비 |
| 생성 이미지 없이 결과물이 밋밋함 | 높음 | 베타 피드백 | 모션·자막 스타일·BGM 품질에 집중, 본인 사진 가이드 |
| YouTube 데이터 보관 정책 위반 | 낮음 | – | `fetched_at` + 30일 정리 작업(G5) |

---

## 9. 바로 시작할 일 (이번 주)

1. [x] §6 결정 D1~D4 확인 — 권장안으로 확정 (2026-10-15, `docs/DECISIONS.md`)
2. [x] FFmpeg 9.0.2 설치 (winget, zoompan/sidechaincompress/ass/xfade 필터 확인)
3. [x] YouTube·Gemini API 키 발급 → `shortforge/.env`에 입력, doctor 통과
4. [x] `git init` + `shortforge/` 골격 + `scripts/doctor.py` + backend venv(uv)
5. [x] PRD/PROMPT v0.2 — G1~G6 반영
6. [x] Step 1 완료: 스키마·저장소·오케스트레이터·Fake 어댑터·비용 가드 (2026-10-15)
7. [x] Step 2 완료: 렌더 스파이크 통과, 30초 영상 약 50초 (2026-10-15)
8. [x] Step 3 완료: 실 API 303 units, 재실행 0 units (2026-10-15)
9. [~] Step 4: 코드·단위 테스트 완료. **Gemini 키 교체 후 `llm_smoke.py --inject`로 실제 Gate 확인 필요**
10. [~] Step 5 / M0: CLI E2E 21초, 테스트 95개. **실제 LLM으로 `new` → `run` 1편 확인 필요 (키 교체 후)**
11. [ ] Step 6 착수: FastAPI 엔드포인트 + Next.js 7탭 UI

> 진행 중 각 Step 완료 시 이 문서의 Gate 체크와 날짜를 갱신한다.
