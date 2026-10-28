---
name: sf-release
description: "ShortForge 사전 배포판(vX.Y.Z-beta.N)을 내는 점검표와 스크립트. 문서 버전 갱신, 새 clone 검증, CI 확인, 태그·GitHub 배포판까지. '배포', '배포 진행', '릴리스', '새 버전 내 줘' 요청이나 sf-releaser가 일할 때 사용한다. 커밋·푸시만 하는 요청에는 쓰지 않는다."
---

# 사전 배포판 내기

공개 저장소 `awesome72/shortforge`(D1: 로컬 설치형). 베타 번호는 태그로만 올리고 패키지 버전(`pyproject.toml`, `app/__init__.__version__`)은 그대로 둔다.

## 점검표 (순서대로, 앞 단계가 성공해야 다음으로)

1. **낼 내용 확인** — `CHANGELOG.md` "다음 버전" 절이 비어 있지 않은지, 작업 트리가 깨끗한지(`git status --short`) 본다. 마지막 태그(`git tag --sort=-creatordate | head -1`)로 다음 번호를 정한다.
2. **문서 버전 갱신**
   ```bash
   python .claude/skills/sf-release/scripts/release_prep.py bump <태그> <YYYY-MM-DD> "<제목>" "<연혁 한 줄>"
   ```
   CHANGELOG 절 열기, README·BETA_RECRUIT·소개 페이지(표시 + 연혁)·PROJECT_PLAN 제목을 바꾼다. 그 뒤 `PROJECT_PLAN.md` 진행 기록 문단에 이번 배포 요약·측정값·테스트 수를 직접 적는다.
3. **커밋·푸시** — 스테이징 파일에 `.env*`, `data/`, `.next*`, `_workspace/`가 없는지 먼저 확인한다(공개 저장소). 커밋 메시지 끝에 저장소 규칙의 공동 작성자 줄을 붙인다.
4. **새 clone 검증** — scratch 폴더에 `git clone` → `shortforge/setup.ps1` → `backend`에서 `uv run pytest -q`. setup의 실패는 "YOUTUBE_API_KEY·GEMINI_API_KEY 비어 있음" 2건만 정상이다. 다른 실패나 테스트 실패가 있으면 멈춘다.
5. **CI 확인** — 방금 커밋의 CI가 `completed success`인지 본다(백엔드 테스트 + 화면 테스트 포함).
   ```bash
   gh run list --branch main --limit 1 --json status,conclusion,headSha
   ```
6. **태그·배포판**
   ```bash
   python .claude/skills/sf-release/scripts/release_prep.py notes <태그> <scratch>/notes.md
   git tag -a <태그> -m "<태그>" && git push origin <태그>
   gh release create <태그> --prerelease --title "<태그> — <제목>" --notes-file <scratch>/notes.md
   ```
7. **보고** — 배포판 주소, 새 clone 테스트 수, CI 결과, 들어간 변경 요약. 이 PC의 `start.bat`으로 새 화면을 보려면 `frontend`에서 `npm run build`가 필요하다는 안내를 붙인다.

## 왜 이 순서인가
- 새 clone 검증: 개발 PC의 `.env` 실제 키에 기대는 테스트가 새 clone에서만 깨진 적이 있다.
- CI 확인 뒤 태그: 태그를 단 뒤 실패를 발견하면 같은 번호를 다시 쓸 수 없다.
- 스크립트가 바꿀 자리를 못 찾으면 아무것도 쓰지 않고 멈춘다: 문서 하나만 버전이 어긋나는 일을 막는다.

## 실패했을 때
- 테스트·CI 실패: 태그를 달지 않고 출력을 보고한다. 고친 뒤 3단계부터 다시 한다(2단계는 이미 반영됨).
- `gh` 인증 만료: 다시 시도하지 말고 사용자에게 `! gh auth login`을 안내한다.
- 이미 있는 태그: 새로 만들지 않고 다음 번호를 쓸지 묻는다.
