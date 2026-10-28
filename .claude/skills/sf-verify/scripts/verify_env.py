"""ShortForge 데이터 사본 검증 환경 (sf-verify 스킬).

    python verify_env.py prepare <대상폴더> [프로젝트ID ...]   # 사본 만들기 (ID 없으면 최근 2개)
    python verify_env.py start <대상폴더> [--web]               # API 8001 (+ 웹 3001) 백그라운드 실행
    python verify_env.py wait [--web]                           # 응답까지 대기
    python verify_env.py cleanup                                # 이 스크립트가 띄운 프로세스만 끄고 tsconfig 정리

원본 shortforge/data/는 읽기만 한다. 서버는 항상 LLM_ADVANCED=off로 띄운다
(.env에 유료 모드가 켜져 있어 검증 중 실제 비용이 나간 적이 있다).
검증 포트가 이미 쓰이고 있으면 띄우지 않는다: 그 서버로 검증하면 원본 데이터와 유료 모드로 돌게 된다.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SF = REPO / "shortforge"
DATA = SF / "data"
API_PORT, WEB_PORT = 8001, 3001
MARK = ".sf-verify"  # prepare가 만든 폴더 표시 (이 표시가 있는 폴더만 지운다)
STATE = Path(tempfile.gettempdir()) / "sf-verify-pids.json"  # start가 띄운 프로세스
TSCONFIG = SF / "frontend" / "tsconfig.json"
VERIFY_DIST = ".next-verify"


def _target(arg: str) -> Path:
    """사본 폴더 경로(절대). 저장소 안이나 원본 데이터의 조상은 거절한다."""
    target = Path(arg).resolve()
    if target == REPO or REPO in target.parents or target in DATA.resolve().parents:
        sys.exit(f"사본 폴더로 쓸 수 없는 경로: {target} (저장소 밖 scratch 폴더를 쓴다)")
    return target


def prepare(target: Path, ids: list[str]) -> None:
    projects = DATA / "projects"
    if not ids:
        dirs = sorted(projects.glob("prj_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        ids = [d.name for d in dirs[:2]]
    if target.exists():
        if not (target / MARK).exists():
            sys.exit(f"{target}가 이미 있고 사본 표시({MARK})가 없다 — 다른 폴더를 고른다")
        shutil.rmtree(target)
    (target / "projects").mkdir(parents=True)
    (target / MARK).write_text("sf-verify 사본", encoding="utf-8")
    for pid in ids:
        shutil.copytree(projects / pid, target / "projects" / pid)
    # 캐시·한도 기록이 든 DB를 복사하고, 목록에는 복사한 프로젝트만 남긴다
    # (남겨 두면 홈 목록에 열리지 않는 프로젝트가 보인다)
    shutil.copy2(DATA / "shortforge.db", target / "shortforge.db")
    with sqlite3.connect(target / "shortforge.db") as con:
        marks = ",".join("?" * len(ids))
        con.execute(f"delete from projects where id not in ({marks})", ids)
        rows = [r[0] for r in con.execute("select id from projects")]
    print(json.dumps({"target": str(target), "projects": ids, "db_rows": len(rows)}, ensure_ascii=False))


def start(target: Path, web: bool) -> None:
    if not (target / MARK).exists():
        sys.exit(f"{target}는 prepare로 만든 사본이 아니다")
    busy = [p for p in ([API_PORT] + ([WEB_PORT] if web else [])) if _listening(p)]
    if busy:
        sys.exit(f"검증 포트 {busy}가 이미 쓰이고 있다 — 그 서버를 확인하고 끈 뒤 다시 한다")
    if web and VERIFY_DIST in TSCONFIG.read_text(encoding="utf-8"):
        sys.exit("tsconfig.json에 이미 .next-verify가 있다 — cleanup을 먼저 한다")
    logs = target / "logs_verify"
    logs.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "LLM_ADVANCED": "off",
        "DATA_DIR": str(target),  # 절대 경로 (상대 경로는 서버가 shortforge/ 기준으로 바꾼다)
        "CORS_ORIGINS": json.dumps([f"http://localhost:{WEB_PORT}", f"http://127.0.0.1:{WEB_PORT}"]),
    }
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    pids = []
    api = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--port", str(API_PORT)],
        cwd=SF / "backend", env=env, creationflags=flags,
        stdout=open(logs / "api.log", "w"), stderr=subprocess.STDOUT,
    )  # fmt: skip
    pids.append(api.pid)
    if web:
        wenv = {
            **os.environ,
            "NEXT_DIST_DIR": VERIFY_DIST,
            "NEXT_PUBLIC_API_BASE": f"http://127.0.0.1:{API_PORT}",
        }
        front = subprocess.Popen(
            ["npx", "next", "dev", "-p", str(WEB_PORT)],
            cwd=SF / "frontend", env=wenv, creationflags=flags, shell=os.name == "nt",
            stdout=open(logs / "web.log", "w"), stderr=subprocess.STDOUT,
        )  # fmt: skip
        pids.append(front.pid)
    STATE.write_text(json.dumps({"pids": pids, "web": web}), encoding="utf-8")
    print(json.dumps({"api": API_PORT, "web": WEB_PORT if web else None, "logs": str(logs)}))


def wait(web: bool, timeout: int = 300) -> None:
    urls = [f"http://127.0.0.1:{API_PORT}/health"] + ([f"http://127.0.0.1:{WEB_PORT}/"] if web else [])
    deadline = time.time() + timeout
    for url in urls:
        while True:
            try:
                urllib.request.urlopen(url, timeout=5)
                print("ready", url)
                break
            except Exception:
                if time.time() > deadline:
                    sys.exit(f"응답 없음: {url} — logs_verify의 로그를 본다")
                time.sleep(2)


def _listening(port: int) -> int | None:
    """그 포트를 듣는 프로세스 ID (Windows netstat)."""
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            return int(parts[4])
    return None


def _clean_tsconfig() -> str:
    """next dev가 넣은 .next-verify 항목만 뺀다 (사용자의 다른 수정은 그대로 둔다)."""
    text = TSCONFIG.read_bytes().decode("utf-8")
    if VERIFY_DIST not in text:
        return "변경 없음"
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = [ln for ln in text.split(nl) if VERIFY_DIST not in ln]
    # 빠진 줄이 배열의 마지막이면 앞 항목의 끝 쉼표가 남아 JSON이 깨지므로 정리한다
    fixed: list[str] = []
    for ln in lines:
        if ln.strip().startswith("]") and fixed and fixed[-1].rstrip().endswith(","):
            fixed[-1] = fixed[-1].rstrip()[:-1]
        fixed.append(ln)
    TSCONFIG.write_bytes(nl.join(fixed).encode("utf-8"))
    json.loads(TSCONFIG.read_text(encoding="utf-8"))  # 깨졌으면 여기서 알린다
    return ".next-verify 항목 제거"


def cleanup() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"pids": []}
    for pid in state["pids"]:  # 이 스크립트가 띄운 프로세스 트리만 끈다
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    STATE.unlink(missing_ok=True)
    time.sleep(1)
    for port in (API_PORT, WEB_PORT):
        left = _listening(port)
        print(port, f"아직 사용 중(PID {left}) — 이 스크립트가 띄운 것이 아니면 그대로 둔다" if left else "비어 있음")
    print("tsconfig.json:", _clean_tsconfig())
    status = subprocess.run(["git", "status", "--short"], cwd=REPO, capture_output=True, text=True).stdout
    print("git status:", status.strip() or "(변경 없음)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔(cp949)에서 한글이 깨지지 않게
    sys.stderr.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "prepare" and len(sys.argv) >= 3:
        prepare(_target(sys.argv[2]), sys.argv[3:])
    elif cmd == "start" and len(sys.argv) >= 3:
        start(_target(sys.argv[2]), "--web" in sys.argv)
    elif cmd == "wait":
        wait("--web" in sys.argv)
    elif cmd == "cleanup":
        cleanup()
    else:
        sys.exit(__doc__)
