"""ShortForge 배포 준비 (sf-release 스킬).

    python release_prep.py bump <새 태그> <날짜> "<배포 제목>" "<연혁 한 줄>"
        CHANGELOG "다음 버전" 아래에 새 버전 절을 열고, README·BETA_RECRUIT·소개 페이지·PROJECT_PLAN 제목의
        버전을 바꾼다. 예: bump v0.3.0-beta.10 2026-10-29 "자막 판" "밝은 장면 자막 판, 피사체 쪽 자르기"
    python release_prep.py notes <태그> <출력 파일>
        CHANGELOG에서 그 버전 절만 뽑아 배포 노트를 만든다 (설치 안내 한 줄을 붙인다).

파일 줄바꿈(CRLF/LF)을 그대로 지킨다. 바꿀 자리를 정확히 한 번 찾지 못하면 아무것도 쓰지 않고 멈춘다.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
INSTALL = (
    "\n설치: Source code (zip)을 받아 `shortforge/setup.bat` → `shortforge/start.bat`. "
    "자세한 안내는 README와 docs/BETA_RECRUIT.md.\n"
)


def _read(rel: str) -> tuple[str, bool]:
    s = (REPO / rel).read_bytes().decode("utf-8")
    return s.replace("\r\n", "\n"), "\r\n" in s


def _write(rel: str, s: str, crlf: bool) -> None:
    (REPO / rel).write_bytes((s.replace("\n", "\r\n") if crlf else s).encode("utf-8"))


def _sub_once(s: str, pattern: str, repl: str, where: str) -> str:
    """정확히 한 곳만 바꾼다. 없거나 여러 곳이면 멈춘다(엉뚱한 자리를 바꾸지 않게)."""
    n = len(re.findall(pattern, s, flags=re.M))
    if n != 1:
        sys.exit(f"{where}: 바꿀 자리가 {n}곳이다 — 정확히 1곳이어야 한다 ({pattern})")
    return re.sub(pattern, repl, s, count=1, flags=re.M)


def bump(tag: str, date: str, title: str, timeline: str) -> None:
    edits: list[tuple[str, str, bool]] = []

    s, crlf = _read("CHANGELOG.md")
    head = "## 다음 버전 (미배포)\n"
    if head not in s:
        sys.exit("CHANGELOG.md: '다음 버전' 절이 없다")
    body = s.split(head, 1)[1].split("\n## ", 1)[0].strip()
    if not body:
        sys.exit("CHANGELOG.md: '다음 버전'이 비어 있다 — 낼 내용이 없다")
    if f"## {tag} " in s:
        sys.exit(f"CHANGELOG.md: {tag} 절이 이미 있다")
    edits.append(("CHANGELOG.md", s.replace(head, f"{head}\n## {tag} — {date} ({title})\n", 1), crlf))

    s, crlf = _read("README.md")
    edits.append(("README.md", _sub_once(s, r"\*\*v\d+\.\d+\.\d+-beta\.\d+\*\*", f"**{tag}**", "README"), crlf))

    s, crlf = _read("docs/BETA_RECRUIT.md")
    s = _sub_once(s, r"`v\d+\.\d+\.\d+-beta\.\d+` 이상", f"`{tag}` 이상", "BETA_RECRUIT")
    edits.append(("docs/BETA_RECRUIT.md", s, crlf))

    s, crlf = _read("docs/intro.html")
    s = _sub_once(s, r"ShortForge · v\d+\.\d+\.\d+-beta\.\d+</div>", f"ShortForge · {tag}</div>", "intro 표시")
    first_li = re.search(r'^( *)<li><span class="when">', s, flags=re.M)
    if not first_li:
        sys.exit("intro.html: 연혁 목록을 찾지 못했다")
    indent = first_li.group(1)
    li = f'{indent}<li><span class="when">{date} · {tag}</span><p>{html.escape(timeline)}</p></li>\n'
    s = s[: first_li.start()] + li + s[first_li.start() :]
    edits.append(("docs/intro.html", s, crlf))

    s, crlf = _read("PROJECT_PLAN.md")
    s = _sub_once(
        s,
        r"^## 현재 상태 \(\d{4}-\d{2}-\d{2} 기준, v\d+\.\d+\.\d+-beta\.\d+\)",
        f"## 현재 상태 ({date} 기준, {tag})",
        "PROJECT_PLAN 제목",
    )
    edits.append(("PROJECT_PLAN.md", s, crlf))

    for rel, text, crlf in edits:  # 모두 찾은 뒤에만 쓴다
        _write(rel, text, crlf)
    print("갱신:", ", ".join(rel for rel, _, _ in edits))
    print("남은 손작업: PROJECT_PLAN.md 진행 기록 문단에 이번 배포 요약·측정값·테스트 수를 적는다")


def notes(tag: str, out: str) -> None:
    s, _ = _read("CHANGELOG.md")
    m = re.search(rf"^## {re.escape(tag)} .*?\n(.*?)(?=^## |\Z)", s, flags=re.M | re.S)
    if not m or not m.group(1).strip():
        sys.exit(f"CHANGELOG.md: {tag} 절이 없거나 비어 있다")
    Path(out).write_text(m.group(1).strip() + "\n" + INSTALL, encoding="utf-8")
    print("노트:", out, f"({len(m.group(1).strip().splitlines())}줄)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔(cp949)에서 한글이 깨지지 않게
    sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) == 6 and sys.argv[1] == "bump":
        bump(*sys.argv[2:6])
    elif len(sys.argv) == 4 and sys.argv[1] == "notes":
        notes(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
