# ShortForge 결정 기록 (Decision Log)

결정을 바꿀 때는 기존 항목을 지우지 말고 상태를 `대체됨`으로 바꾼 뒤 새 항목을 추가한다.

| ID | 결정 | 상태 | 날짜 |
|---|---|---|---|
| D1 | MVP 배포 형태는 **로컬 설치형**으로 한다 | 확정 | 2026-10-15 |
| D2 | M0는 **CLI + Project JSON 파일**로 E2E를 검증한다. 웹 UI는 M1에서 Next.js로 한 번만 만든다 | 확정 | 2026-10-15 |
| D3 | 기본 LLM은 **Gemini 무료 등급**으로 한다. Ollama 어댑터는 유지하되 소형 모델 스모크 테스트만 한다 | 확정 | 2026-10-15 |
| D4 | 기본 이미지 경로는 **본인 사진 업로드 + 프롬프트 내보내기**로 한다. ComfyUI는 원격 GPU 장비용 선택 어댑터로 둔다 | 확정 | 2026-10-15 |
| D5 | 유료 플랜의 가치는 M2 베타 데이터로 결정한다 | 보류 | 2026-10-15 |
| D6 | 레퍼런스 주제 관련성은 **S2 안에서 LLM으로 판정**한다(b안). 무관한 후보는 뒤로 보내고 기본 선택에서 뺀다. 판정이 실패하면 점수 순으로 진행한다 | 확정 | 2026-10-15 |
| D8 | MeloTTS 비교는 **M3(상업 이용 전환 시점)으로 미룬다**. MVP는 Edge-TTS | 확정 | 2026-10-15 |
| D9 | 사용자 녹음 음성 + faster-whisper 자막(7-4)은 사용자 결정 후 진행 | 보류 | 2026-10-15 |
| D10 | M1 패키징은 **Windows 설치·실행 스크립트**(`setup.bat`, `start.bat`)로 한다. Docker는 개발 PC에 없어(Windows Home, RAM 8GB) 검증할 수 없으므로 M2 이후에 다룬다 | 확정 | 2026-10-15 |
| D11 | Gemini는 **작업별 모델 분리**: S3·S4는 `GEMINI_MODEL`(3.8-flash), S1·S2 관련성·S6는 `GEMINI_MODEL_LIGHT`(3.5-flash-lite). 주 모델의 일일 한도가 바닥나면 경량 모델로 자동 대체하고 단계 경고로 알린다 | 확정 | 2026-10-15 |
| D12 | 무료 이미지는 **소스 체인**으로 연동한다: 본인 사진 → Cloudflare Workers AI(FLUX.2 klein 4B, 720×1280, seed 지정) → **Pixabay** 무료 사진(`stock`) → 프롬프트 내보내기. `IMAGE_MODE=cloudflare,stock`. Pexels는 `pexels`로 명시할 때만 쓴다. Gemini 이미지·Pollinations·Hugging Face는 쓰지 않는다 | 확정 | 2026-10-15 |
| D7 | Gemini 모델은 **버전을 고정한 이름**(`gemini-3.8-flash`)을 쓴다. 별칭(`*-latest`)은 쓰지 않는다. 키는 **결제가 연결되지 않은 프로젝트**에서 발급한다 | 확정 | 2026-10-15 |

## 근거

- **D1.** 호스팅형은 GPU 서버 비용이 생겨 "비용 ₩0" 원칙과 충돌한다. 발표 자료의 제안과도 같다.
- **D2.** PRD의 M0는 Streamlit, M1은 Next.js라 2주짜리 화면을 버리게 된다. 계획서 G1을 참조한다.
- **D3.** 개발 PC는 RAM 8GB에 GPU가 없어 Ollama로는 3B급 모델만 돌릴 수 있고, 한국어 품질이 불확실하다. Gemini 무료 정책이 바뀔 때를 대비해 어댑터 교체 경로는 유지한다.
- **D4.** 개발 PC에 GPU가 없다(Intel UHD 620). PRD 리스크 표에서 "GPU 없는 사용자"의 가능성이 높다고 본 것과도 맞는다.
- **D6.** 실측에서 `order=viewCount` 검색이 "퇴근 후 홈트"에 어깨 운동 영상을 2위로 올렸다. 검색 순서를 바꾸면 조회수 높은 영상이 덜 잡히고, 사용자 수동 해제만으로는 기본 선택이 틀린다. LLM 판정은 쿼터 0, 호출 1회다.
- **D8.** MeloTTS는 PyTorch(수 GB)가 필요해 RAM 8GB 노트북에 부담이 크다. Edge-TTS의 리스크는 상업 이용 조건이고, MVP(로컬·비상업 베타)에서는 문제가 되지 않는다.
- **D11.** 실측 결과 3.8-flash 무료 등급은 프로젝트·모델당 **하루 20회**였다(`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). 프로젝트 1편에 LLM 호출이 5~7회이므로 하루 3~4편이 한계다. 한도는 모델마다 따로라, 가벼운 작업을 경량 모델로 보내면 주 모델 호출은 1편당 2~4회(S3, S4 재시도)로 줄어 하루 5~10편이 된다. 일일 한도 429는 기다려도 풀리지 않으므로(retryDelay 약 19시간) 대기하지 않는다.
- **D12.** 2026-10 조사 결과는 다음과 같다. Cloudflare는 매일 10,000 Neurons를 무료로 준다(공식). 체험판 크레딧이 아니라 매일 다시 채워지는 한도라 ₩0 원칙에 맞는다. FLUX.1 schnell은 입력이 `prompt`·`steps`뿐이라(`additionalProperties: false`) 9:16과 seed를 지정할 수 없다. 그래서 multipart로 width·height·seed를 받는 klein 4B를 기본으로 한다(720×1280 = 6타일 × 26.05 ≈ 156 Neurons, 하루 약 64장). Gemini 이미지는 최근 자료상 API 무료 등급이 없다. Pollinations는 2026-07 무료 무키 등급이 종료됐다. Hugging Face는 월 $0.10 이하라 사실상 체험판이다. 무료 사진은 실제 사진이라 "내 체험" 이야기에 자연스럽다. 처음에는 Pexels로 정했지만, 2026-10-15 확인 결과 Pexels API 페이지에 **"New API key issuance is currently paused"** 공지가 있어 신규 키를 받을 수 없었다. 그래서 기본을 Pixabay로 바꿨다(무료 키 발급 가능, 60초당 100회). Pixabay 약관은 검색 요청을 24시간 캐시하고, 이미지를 직접 링크하지 말고 내려받아 쓰며, 출처를 표기하도록 요구한다. 어댑터가 이를 모두 지킨다. 식별 가능한 인물 사진은 초상권에 주의한다. 생성 이미지는 장면마다 인물이 달라지므로 프롬프트를 손·물건·공간 위주로 만든다.
- **D7.** `gemini-2.5-flash`는 목록에는 나오지만 신규 사용자에게 404를 냈다. 처음 받은 키는 선결제(prepay) 프로젝트 소속이라 402(크레딧 소진)가 났다. 결제가 연결된 프로젝트는 유료 등급으로 모든 호출이 과금되므로 ₩0 원칙과 충돌한다. `doctor.py --probe-llm`으로 확인한다.

## 함께 반영한 문서 정합성 수정 (PRD/PROMPT v0.2)

| # | 수정 내용 |
|---|---|
| G1 | M0 화면을 Streamlit에서 CLI로 바꿈 (D2) |
| G2 | 레퍼런스 최대 길이를 `REF_MAX_DURATION_SEC`(기본 60초) 설정값으로 바꿈. Shorts는 최대 180초까지 가능 |
| G3 | 자막은 Edge-TTS 단어 타이밍(WordBoundary)으로 SRT를 만드는 것을 기본으로 하고, faster-whisper는 사용자 녹음 음성일 때만 씀 |
| G4 | S2 쿼터 설계값을 약 306 units/회로 명시함 (search 3×100 + videos/channels 2 + commentThreads 4). 상한은 ≤400 units 유지 |
| G5 | `refs[].fetched_at`을 추가하고, 30일이 지나면 재조회하거나 정리함. 정확한 보관 조건은 YouTube API Developer Policy로 확인 필요 |
| G6 | 개발은 네이티브(uv + npm)로 하고, `docker compose`는 M1 패키징 단계에서 검증함 |
