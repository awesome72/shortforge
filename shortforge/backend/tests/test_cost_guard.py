"""비용 ₩0 가드 (PROJECT_PROMPT §2-1, DoD "비용이 발생할 수 있는 코드 경로 0개").

- 과금 API SDK를 import하는 코드가 없어야 한다.
- pyproject 의존성은 허용 목록 안에 있어야 한다. 새 의존성은 리뷰 후 여기에 추가한다.
"""

import ast
import re
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

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


def test_no_paid_sdk_imports():
    offenders = []
    for py in (BACKEND / "app").rglob("*.py"):
        for name in _imports(py):
            if any(name == m or name.startswith(m + ".") for m in FORBIDDEN_MODULES):
                offenders.append(f"{py.relative_to(BACKEND)}: {name}")
    assert not offenders, offenders


def test_dependencies_whitelisted():
    data = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    deps = {
        re.split(r"[\[<>=!~ ]", d, maxsplit=1)[0].lower() for d in data["project"]["dependencies"]
    }
    assert deps <= ALLOWED_DEPENDENCIES, deps - ALLOWED_DEPENDENCIES
