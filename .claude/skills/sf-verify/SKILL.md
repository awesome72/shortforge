---
name: sf-verify
description: "ShortForge 변경을 데이터 사본으로 실제 실행해 확인하는 절차와 스크립트. 검증 서버(API 8001·웹 3001, 유료 모드 끔) 띄우기, API 흐름·렌더 프레임·화면 캡처 확인, 정리까지. '실제로 확인', '사본으로 검증', '렌더해서 봐 줘', '화면 캡처' 요청이나 sf-verifier가 일할 때 사용한다. 자동 테스트(pytest·e2e)만 돌리면 되는 경우에는 쓰지 않는다."
---

# 데이터 사본 검증

자동 테스트는 Fake 어댑터라 실제 FFmpeg 렌더, 실제 무료 API(Pixabay·Gemini), 실제 화면을 못 본다. 이 절차는 그 틈을 사용자의 실제 데이터를 건드리지 않고 메운다.

## 순서

1. **사본 만들기** — scratch 폴더(세션 scratchpad)에 둔다.
   ```bash
   python .claude/skills/sf-verify/scripts/verify_env.py prepare "<scratch>/data_verify" [prj_... ...]
   ```
   ID를 안 주면 최근 2개 프로젝트를 복사한다. 동영상·밝은 장면 같은 특정 상황이 필요하면 그런 프로젝트를 골라 준다.
2. **서버 띄우기** — `start ... [--web]` 뒤 `wait [--web]`(웹을 띄웠으면 `--web`도 준다). API만 필요하면 `--web`을 빼서 빠르게 한다(웹 dev 서버 첫 컴파일은 1~3분).
3. **확인** — 아래 "확인 방법"에서 필요한 것만.
4. **정리 (반드시)** — `verify_env.py cleanup`. 이 스크립트가 띄운 프로세스 트리만 끄고, `tsconfig.json`에서 `.next-verify` 항목만 빼고, `git status`를 보여 준다. 포트가 이미 쓰이고 있으면 `start`가 멈춘다: 그 서버로 검증하면 원본 데이터와 유료 모드로 돌게 된다.

## 지켜야 할 것과 이유
- **유료 모드 끔**: 스크립트가 `LLM_ADVANCED=off`를 넣는다. 직접 띄울 때도 꼭 넣는다. `.env`는 유료 모드가 켜져 있다.
- **원본 데이터 금지**: `shortforge/data/`에 쓰지 않는다. 사용자의 프로젝트와 무료 한도 기록이 있다.
- **사용자 서버 보호**: 3000·8000(start.bat)은 건드리지 않는다. 검증은 3001·8001만.
- **봇 차단을 우회하지 않는다**: 외부 사이트가 스크립트 요청을 403으로 막으면 브라우저처럼 위장하지 말고 "확인 못 함"으로 보고한다(Pixabay 썸네일에서 실제로 막혔다).
- **설정 API 금지**: 검증 서버도 실제 `shortforge/.env`를 쓴다. `/settings/keys`·`/settings/advanced`·`/settings/brand`를 부르면 사용자의 `.env`가 바뀐다.
- **한도 기록은 사본에만 쌓인다**: 검증 중 쓴 YouTube·Cloudflare·Pixabay 요청은 사본 DB에만 기록되어, 같은 날 원본의 남은 한도 표시가 실제보다 넉넉하게 보인다. 무료 API는 필요한 만큼만 부르고 보고에 사용량을 적는다.
- **큰 다운로드·유료 호출 금지**: 무료 API도 필요한 만큼만 부른다(Pixabay 검색은 24시간 캐시되어 다시 불러도 요청이 늘지 않는다).

## 확인 방법

**API 흐름** — `urllib`로 부르고 `Origin: http://localhost:3001` 헤더를 붙인다(쓰기 요청은 Origin 검사). 실행은 202로 바로 돌아오므로 `GET /projects/{id}`의 `busy`가 거짓이 될 때까지 기다린다.

**렌더 결과** — `render/render.log`(`[timing]`, `caption luma`, `measure`), `render.checks`, `render.quality`를 본다. 프레임은 FFmpeg로 뽑아 이어 붙여 한 장으로 본다:
```bash
F="$LOCALAPPDATA/Microsoft/WinGet/Links/ffmpeg.exe"
"$F" -loglevel error -y -ss 6.0 -i final.mp4 -frames:v 1 -vf scale=270:480 f0.jpg
"$F" -loglevel error -y -i f0.jpg -i f1.jpg -filter_complex hstack=inputs=2 sheet.jpg
```
그 뒤 Read 도구로 이미지를 본다.

**화면** — Playwright(Python, Edge 사용, 브라우저를 따로 받지 않음):
```bash
uv run --no-project --python 3.11 --with playwright==1.48.0 python <스크립트>
```
Python 3.11을 지정한다(지정하지 않으면 greenlet 빌드가 실패한다). 페이지 열기 시간 제한은 넉넉히(`set_default_navigation_timeout(240000)`): dev 서버의 첫 컴파일이 느리다. 콘솔 오류를 모으고, 휴대폰 폭(390px)에서 `scrollWidth > innerWidth`를 확인한다.

## 보고 형식
항목별로: 무엇을 → 결과(수치·파일 경로·캡처 경로) → 판정(통과 / 문제 / 확인 못 함 + 이유). 렌더 시간은 PC 부하에 따라 52초~5분으로 흔들리니 비교할 때는 같은 조건에서 잰다.
