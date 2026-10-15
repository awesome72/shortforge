"""ShortForge 환경 점검 (PROJECT_PLAN Step 0 Gate).

사용법:
    python scripts/doctor.py            # 전체 점검 (API 키 실제 검증 포함)
    python scripts/doctor.py --offline  # 네트워크 호출 없이 로컬 항목만
    python scripts/doctor.py --probe-llm  # Gemini 실제 호출로 사용 가능·결제 연결 여부까지 확인

표준 라이브러리만 사용한다. 키 검증은 비용이 들지 않는 호출만 쓴다:
- YouTube: i18nLanguages.list (1 unit)
- Gemini:  models.list (무료, 생성 호출 아님)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # shortforge/
BACKEND = ROOT / "backend"
ENV_FILE = ROOT / ".env"
WINGET_LINKS = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"

OK, WARN, FAIL = "OK", "WARN", "FAIL"
results: list[tuple[str, str, str]] = []


def report(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def find_exe(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    candidate = WINGET_LINKS / f"{name}.exe"
    return str(candidate) if candidate.exists() else None


def first_line(cmd: list[str]) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return (out.stdout or out.stderr).splitlines()[0] if (out.stdout or out.stderr) else ""


# 기본 "Python-urllib" User-Agent는 Pixabay 앞단의 봇 차단에 걸린다(403, error code 1010)
USER_AGENT = "ShortForge-doctor/0.1"


def http_json(url: str, timeout: int = 15, data: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if data is not None:
        req.data = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        # 0 = 응답을 받지 못함. 점검 하나가 실패해도 결과 표는 끝까지 출력한다
        return 0, {"error": {"message": f"응답 없음 ({type(e).__name__}: {e})"}}


# ── 로컬 점검 ──────────────────────────────────────────────


def check_python() -> None:
    v = sys.version_info
    if (3, 11) <= (v.major, v.minor) < (3, 13):
        report(OK, "Python", f"{v.major}.{v.minor}.{v.micro}")
    else:
        report(FAIL, "Python", f"{v.major}.{v.minor} — 3.11~3.12 필요")


def check_ffmpeg() -> None:
    for name in ("ffmpeg", "ffprobe"):
        exe = find_exe(name)
        if not exe:
            report(FAIL, name, "미설치 — winget install Gyan.FFmpeg")
            continue
        line = first_line([exe, "-version"])
        detail = line.split(" Copyright")[0]
        if name == "ffmpeg":
            filters = subprocess.run(
                [exe, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30
            ).stdout
            missing = [f for f in ("zoompan", "sidechaincompress", "ass", "xfade") if f" {f} " not in filters]
            if missing:
                report(FAIL, name, f"{detail} — 필터 누락: {', '.join(missing)}")
                continue
            detail += " (zoompan/sidechaincompress/ass/xfade 확인)"
        report(OK, name, detail)


def check_venv() -> None:
    venv_py = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not venv_py.exists():
        report(FAIL, "backend venv", "없음 — cd backend && uv sync")
        return
    code = "import fastapi, pydantic, sqlmodel, edge_tts, google.genai; print(pydantic.VERSION)"
    out = subprocess.run([str(venv_py), "-c", code], capture_output=True, text=True, timeout=60)
    if out.returncode == 0:
        report(OK, "backend venv", f"패키지 import 성공 (pydantic {out.stdout.strip()})")
    else:
        report(FAIL, "backend venv", out.stderr.strip().splitlines()[-1])


def check_env(env: dict[str, str]) -> None:
    if not ENV_FILE.exists():
        report(FAIL, ".env", "없음 — .env.example을 .env로 복사")
        return
    report(OK, ".env", str(ENV_FILE))
    if not env.get("YOUTUBE_API_KEY"):
        report(FAIL, "YOUTUBE_API_KEY", "비어 있음")
    mode = env.get("LLM_MODE", "gemini")
    if mode == "gemini" and not env.get("GEMINI_API_KEY"):
        report(FAIL, "GEMINI_API_KEY", "비어 있음 (LLM_MODE=gemini)")


def check_disk() -> None:
    free_gb = shutil.disk_usage(ROOT).free / 1024**3
    status = OK if free_gb >= 10 else WARN
    report(status, "디스크 여유", f"{free_gb:.1f} GB" + ("" if status == OK else " — 10GB 이상 권장"))


# ── 온라인 점검 ────────────────────────────────────────────


def check_youtube(key: str) -> None:
    if not key:
        return
    q = urllib.parse.urlencode({"part": "snippet", "hl": "ko", "key": key})
    status, body = http_json(f"https://www.googleapis.com/youtube/v3/i18nLanguages?{q}")
    if status == 200:
        report(OK, "YouTube API", "키 유효 (점검 비용 1 unit)")
    else:
        reason = body.get("error", {}).get("message", f"HTTP {status}")
        report(FAIL, "YouTube API", reason)


def check_gemini(key: str, model: str, probe: bool) -> None:
    if not key:
        return
    q = urllib.parse.urlencode({"key": key, "pageSize": 200})
    status, body = http_json(f"https://generativelanguage.googleapis.com/v1beta/models?{q}")
    if status != 200:
        report(FAIL, "Gemini API", body.get("error", {}).get("message", f"HTTP {status}"))
        return
    names = [m["name"].removeprefix("models/") for m in body.get("models", [])]
    if model not in names:
        flash = sorted(n for n in names if "flash" in n)[-6:]
        report(FAIL, "Gemini API", f"키 유효, 단 {model} 없음 — 후보: {', '.join(flash)}")
        return
    if not probe:
        # 목록에 있어도 실제 호출은 막혀 있을 수 있다 (예: 신규 사용자 미제공 404, 결제 402)
        report(WARN, "Gemini API", f"키 유효, {model} 목록에 있음 — 실제 호출 확인은 --probe-llm")
        return
    status, body = http_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?"
        + urllib.parse.urlencode({"key": key}),
        data={
            "contents": [{"parts": [{"text": "ok"}]}],
            "generationConfig": {"maxOutputTokens": 1},
        },
        timeout=60,  # Gemini 3.x는 첫 응답에 사고 시간이 붙어 15초를 넘길 수 있다
    )
    msg = body.get("error", {}).get("message", f"HTTP {status}") if status != 200 else ""
    if status == 200:
        report(OK, "Gemini API", f"{model} 실제 호출 성공")
    elif status == 402 or "billing" in msg.lower() or "prepay" in msg.lower():
        report(
            FAIL,
            "Gemini API",
            f"결제가 연결된 프로젝트의 키다 (HTTP {status}) — 비용 ₩0 원칙 위반. "
            "결제가 없는 새 프로젝트에서 키를 다시 만든다",
        )
    elif status == 0:
        report(WARN, "Gemini API", f"{model} 응답이 60초 안에 오지 않았다 — 잠시 후 다시 점검. {msg}")
    elif status == 429:
        report(WARN, "Gemini API", "분당·일일 호출 한도에 걸렸다 — 잠시 후 다시 점검")
    else:
        report(FAIL, "Gemini API", f"{model} 호출 실패 (HTTP {status}): {msg}")


def check_images(env: dict[str, str]) -> None:
    """IMAGE_MODE에 든 무료 이미지 소스의 키를 비용 없이 확인한다 (D12)."""
    sources = [t.strip() for t in env.get("IMAGE_MODE", "upload").split(",")]
    if "cloudflare" in sources:
        account, token = env.get("CLOUDFLARE_ACCOUNT_ID", ""), env.get("CLOUDFLARE_API_TOKEN", "")
        if not account or not token:
            report(FAIL, "Cloudflare", "CLOUDFLARE_ACCOUNT_ID·CLOUDFLARE_API_TOKEN이 비어 있다")
        else:
            req = urllib.request.Request(
                "https://api.cloudflare.com/client/v4/user/tokens/verify",
                headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
            )
            err: object = "응답의 success가 false"
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    ok = json.loads(r.read()).get("success")
            except Exception as e:
                ok, err = False, e
            if ok:
                report(OK, "Cloudflare", "API 토큰 유효 (이미지 무료 하루 10,000 Neurons)")
            else:
                report(FAIL, "Cloudflare", f"API 토큰 확인 실패 — Workers AI 권한 토큰인지 확인 ({err})")
    if "stock" in sources or "pixabay" in sources:
        key = env.get("PIXABAY_API_KEY", "")
        if not key:
            report(FAIL, "Pixabay", "PIXABAY_API_KEY가 비어 있다 (pixabay.com/api/docs/ 의 key)")
        else:
            q = urllib.parse.urlencode({"key": key, "q": "office", "per_page": 3})
            status, body = http_json(f"https://pixabay.com/api/?{q}")
            if status == 200:
                report(OK, "Pixabay", f"API 키 유효 (검색 결과 {body.get('totalHits', 0)}개)")
            else:
                report(FAIL, "Pixabay", f"API 키 확인 실패 HTTP {status} — 키를 다시 복사한다")
    if "pexels" in sources:
        key = env.get("PEXELS_API_KEY", "")
        if not key:
            report(FAIL, "Pexels", "PEXELS_API_KEY가 비어 있다")
        else:
            req = urllib.request.Request(
                "https://api.pexels.com/v1/search?query=office&per_page=1",
                headers={"Authorization": key, "User-Agent": USER_AGENT},
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    report(OK, "Pexels", f"API 키 유효 (남은 요청 {r.headers.get('X-Ratelimit-Remaining', '?')})")
            except urllib.error.HTTPError as e:
                report(FAIL, "Pexels", f"API 키 확인 실패 HTTP {e.code}")
            except Exception as e:
                report(WARN, "Pexels", f"응답 없음 ({type(e).__name__})")


def check_edge_tts() -> None:
    venv_py = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not venv_py.exists():
        return
    code = (
        "import asyncio, edge_tts\n"
        "async def m():\n"
        "    vs = await edge_tts.list_voices()\n"
        "    print(','.join(v['ShortName'] for v in vs if v['Locale']=='ko-KR'))\n"
        "asyncio.run(m())"
    )
    out = subprocess.run([str(venv_py), "-c", code], capture_output=True, text=True, timeout=60)
    if out.returncode == 0 and out.stdout.strip():
        report(OK, "Edge-TTS", f"ko-KR 음성: {out.stdout.strip()}")
    else:
        report(FAIL, "Edge-TTS", (out.stderr.strip().splitlines() or ["응답 없음"])[-1])


def check_ollama(env: dict[str, str]) -> None:
    host = env.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        status, body = http_json(f"{host}/api/tags", timeout=3)
        models = [m["name"] for m in body.get("models", [])]
        report(OK, "Ollama (선택)", f"실행 중, 모델: {', '.join(models) or '없음'}")
    except Exception:
        report(WARN, "Ollama (선택)", "미실행 — 로컬 LLM 모드는 Step 4 스모크 테스트에서 설정")


def main() -> int:
    parser = argparse.ArgumentParser(description="ShortForge 환경 점검")
    parser.add_argument("--offline", action="store_true", help="네트워크 점검 생략")
    parser.add_argument(
        "--probe-llm",
        action="store_true",
        help="Gemini에 1토큰짜리 실제 호출을 보내 사용 가능 여부와 결제 연결 여부를 확인",
    )
    args = parser.parse_args()

    env = load_env()
    check_python()
    check_ffmpeg()
    check_venv()
    check_env(env)
    check_disk()
    if not args.offline:
        check_youtube(env.get("YOUTUBE_API_KEY", ""))
        check_gemini(
            env.get("GEMINI_API_KEY", ""),
            env.get("GEMINI_MODEL", "gemini-3.8-flash"),
            args.probe_llm,
        )
        check_images(env)
        check_edge_tts()
        check_ollama(env)

    width = max(len(n) for _, n, _ in results)
    for status, name, detail in results:
        print(f"[{status:<4}] {name:<{width}}  {detail}")
    fails = sum(1 for s, _, _ in results if s == FAIL)
    print(f"\n결과: {'통과' if fails == 0 else f'실패 {fails}건'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
