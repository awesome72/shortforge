# ShortForge 결정 기록 (Decision Log)

결정을 바꿀 때는 기존 항목을 지우지 말고 상태를 `대체됨`으로 바꾼 뒤 새 항목을 추가한다.

| ID | 결정 | 상태 | 날짜 |
|---|---|---|---|
| D1 | MVP 배포 형태는 **로컬 설치형**으로 한다 | 확정 | 2026-10-15 |
| D2 | M0는 **CLI + Project JSON 파일**로 E2E를 검증한다. 웹 UI는 M1에서 Next.js로 한 번만 만든다 | 확정 | 2026-10-15 |
| D3 | 기본 LLM은 **Gemini 무료 등급**으로 한다. Ollama 어댑터는 유지하되 소형 모델 스모크 테스트만 한다 | 확정 | 2026-10-15 |
| D4 | 기본 이미지 경로는 **본인 사진 업로드 + 프롬프트 내보내기**로 한다. ComfyUI는 원격 GPU 장비용 선택 어댑터로 둔다 | 확정 | 2026-10-15 |
| D5 | 유료 플랜의 가치는 M2 베타 데이터로 결정한다 | 보류 | 2026-10-15 |

## 근거

- **D1.** 호스팅형은 GPU 서버 비용이 생겨 "비용 ₩0" 원칙과 충돌한다. 발표 자료의 제안과도 같다.
- **D2.** PRD의 M0는 Streamlit, M1은 Next.js라 2주짜리 화면을 버리게 된다. 계획서 G1을 참조한다.
- **D3.** 개발 PC는 RAM 8GB에 GPU가 없어 Ollama로는 3B급 모델만 돌릴 수 있고, 한국어 품질이 불확실하다. Gemini 무료 정책이 바뀔 때를 대비해 어댑터 교체 경로는 유지한다.
- **D4.** 개발 PC에 GPU가 없다(Intel UHD 620). PRD 리스크 표에서 "GPU 없는 사용자"의 가능성이 높다고 본 것과도 맞는다.

## 함께 반영한 문서 정합성 수정 (PRD/PROMPT v0.2)

| # | 수정 내용 |
|---|---|
| G1 | M0 화면을 Streamlit에서 CLI로 바꿈 (D2) |
| G2 | 레퍼런스 최대 길이를 `REF_MAX_DURATION_SEC`(기본 60초) 설정값으로 바꿈. Shorts는 최대 180초까지 가능 |
| G3 | 자막은 Edge-TTS 단어 타이밍(WordBoundary)으로 SRT를 만드는 것을 기본으로 하고, faster-whisper는 사용자 녹음 음성일 때만 씀 |
| G4 | S2 쿼터 설계값을 약 306 units/회로 명시함 (search 3×100 + videos/channels 2 + commentThreads 4). 상한은 ≤400 units 유지 |
| G5 | `refs[].fetched_at`을 추가하고, 30일이 지나면 재조회하거나 정리함. 정확한 보관 조건은 YouTube API Developer Policy로 확인 필요 |
| G6 | 개발은 네이티브(uv + npm)로 하고, `docker compose`는 M1 패키징 단계에서 검증함 |
