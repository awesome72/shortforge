"""비용 가드 (PROJECT_PROMPT §2-1, D13).

기본 경로는 비용 ₩0이다. 유료 LLM은 사용자가 직접 켜는 고급 모드(D13)에서만 쓴다.
- 과금 API SDK는 `app/adapters/llm/advanced/` 밖에서 import하지 않는다.
- 기본 설정으로 서버를 띄우면 유료 SDK 모듈이 로드되지 않고, 유료 어댑터도 만들어지지 않는다.
- pyproject 의존성은 허용 목록 안에 있어야 한다. 새 의존성은 리뷰 후 여기에 추가한다.
"""

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ADVANCED_DIR = BACKEND / "app" / "adapters" / "llm" / "advanced"
# 고급 모드(D13)에서만 쓰는 유료 LLM SDK. ADVANCED_DIR 안에서만 import할 수 있다
ADVANCED_ONLY = {"anthropic", "openai"}

FORBIDDEN_MODULES = {
    "openai",
    "anthropic",
    "elevenlabs",
    "replicate",
    "runwayml",
    "stability_sdk",
    "fal_client",
    "lumaai",
    "google.cloud.texttospeech",
    "google.cloud.aiplatform",
    "vertexai",
}

ALLOWED_DEPENDENCIES = {
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    "sqlmodel",
    "httpx",
    "edge-tts",
    "google-genai",  # Gemini 무료 등급만. 유료 모델·Vertex 경로는 쓰지 않는다
    "python-multipart",  # FastAPI 사진 업로드(multipart) 파싱. 로컬 처리
    "tzdata",  # 시간대 DB (Windows에는 없음). YouTube 쿼터의 PT 자정 기준 계산용
    "anthropic",  # 고급 모드(D13) 전용. advanced/ 안에서만 쓰고 기본 설정에서는 로드하지 않는다
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _is(name: str, modules: set[str]) -> bool:
    return any(name == m or name.startswith(m + ".") for m in modules)


def test_no_paid_sdk_imports():
    offenders = []
    for py in (BACKEND / "app").rglob("*.py"):
        advanced = ADVANCED_DIR in py.parents
        for name in _imports(py):
            if not _is(name, FORBIDDEN_MODULES):
                continue
            if advanced and _is(name, ADVANCED_ONLY):
                continue  # 고급 모드 모듈 안의 유료 LLM SDK만 허용
            offenders.append(f"{py.relative_to(BACKEND)}: {name}")
    assert not offenders, offenders


def test_default_server_loads_no_paid_sdk():
    """기본 설정으로 API 서버를 조립하면 유료 SDK 모듈이 메모리에 올라오지도 않는다."""
    code = f"""
import sys, tempfile
from pathlib import Path
from app.config import Settings
from app.adapters.registry import build_adapters
import app.main
s = Settings(_env_file=None, data_dir=Path(tempfile.mkdtemp()))
build_adapters(s, problems=[])
app.main.create_app(s)
bad = sorted(m for m in sys.modules if m.split('.')[0] in {sorted(ADVANCED_ONLY)!r})
print(','.join(bad))
"""
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", f"기본 설정에서 유료 SDK가 로드됐다: {out.stdout}"


def test_default_settings_build_no_paid_adapter():
    from app.adapters.registry import build_adapters
    from app.config import Settings

    adapters = build_adapters(Settings(_env_file=None), problems=[])
    mod = type(adapters.llm).__module__
    assert ".advanced" not in mod and "Routed" not in type(adapters.llm).__name__


def test_dependencies_whitelisted():
    data = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    deps = {
        re.split(r"[\[<>=!~ ]", d, maxsplit=1)[0].lower() for d in data["project"]["dependencies"]
    }
    assert deps <= ALLOWED_DEPENDENCIES, deps - ALLOWED_DEPENDENCIES
