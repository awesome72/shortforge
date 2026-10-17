"""서버 로그와 문제 보고용 파일 (베타 지원).

- 로그: `data/logs/app.log` (1MB × 3개 순환). 단계 실패는 traceback까지 남는다.
- 문제 보고 파일: 로그·환경 정보·KPI 이벤트(주제·대사 없음)를 zip 하나로 묶는다.
  프로젝트를 고르면 그 프로젝트의 project.json과 렌더 로그도 넣는다(주제·대사가 들어 있다).
- 비밀값(API 키·토큰)은 로그와 zip 어디에도 남기지 않는다. 설정값은 "설정됨/비어 있음"으로만 적고,
  로그와 파일 내용에서 실제 키 문자열과 `key=...` 쿼리를 지운다.
"""

from __future__ import annotations

import io
import json
import logging
import platform
import re
import sys
import zipfile
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import __version__
from app.config import Settings
from app.media import find_exe

LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3
SECRET_FIELD = re.compile(r"(key|token|secret|password)", re.I)
KEY_PARAM = re.compile(r"(?i)\b(key|api_key|token|access_token)=[^&\s\"']+")
LOGGERS = ("app", "uvicorn.error")


def app_version() -> str:
    return __version__


def secret_values(settings: Settings) -> list[str]:
    out = []
    for name, value in settings.model_dump().items():
        if SECRET_FIELD.search(name) and isinstance(value, str) and len(value) >= 6:
            out.append(value)
    return out


def scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        text = text.replace(s, "[숨김]")
    return KEY_PARAM.sub(lambda m: f"{m.group(1)}=[숨김]", text)


class _ScrubFilter(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self.secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        record.msg, record.args = scrub(msg, self.secrets), None
        if record.exc_text:
            record.exc_text = scrub(record.exc_text, self.secrets)
        return True


def log_dir(settings: Settings) -> Path:
    return settings.data_dir / "logs"


def setup_logging(settings: Settings) -> Path:
    """app.*·uvicorn.error 로그를 data/logs/app.log에 남긴다. 여러 번 불러도 핸들러는 하나다."""
    path = log_dir(settings) / "app.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8", delay=True
    )
    handler.set_name("shortforge-file")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(_ScrubFilter(secret_values(settings)))
    for name in LOGGERS:
        logger = logging.getLogger(name)
        for h in list(logger.handlers):
            if h.get_name() == "shortforge-file":
                logger.removeHandler(h)
                h.close()
        logger.addHandler(handler)
        if logger.level == logging.NOTSET or logger.level > logging.INFO:
            logger.setLevel(logging.INFO)
    logging.getLogger("app").info("ShortForge %s 시작 (data=%s)", app_version(), settings.data_dir)
    return path


def _has_exe(name: str) -> bool:
    try:
        return bool(find_exe(name))
    except Exception:  # noqa: BLE001 - 없으면 MediaError
        return False


def environment(settings: Settings, setup_problems: list[str]) -> dict:
    """문제 보고에 넣을 환경 정보. 비밀값은 설정 여부만 적는다."""
    config = {}
    for name, value in settings.model_dump(mode="json").items():
        if SECRET_FIELD.search(name):
            config[name] = "설정됨" if value else "비어 있음"
        elif name == "comfyui_url" and value:
            config[name] = "설정됨"
        else:
            config[name] = value
    return {
        "shortforge": app_version(),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "ffmpeg": _has_exe("ffmpeg"),
        "ffprobe": _has_exe("ffprobe"),
        "setup_problems": setup_problems,
        "settings": config,
    }


README = """ShortForge 문제 보고 파일

들어 있는 것
- environment.json: 버전, OS, FFmpeg 유무, 설정값 (API 키·토큰은 '설정됨/비어 있음'으로만 적음)
- logs/: 서버 로그 (단계 오류의 상세 내용)
- metrics.jsonl: 사용 통계 (프로젝트 ID·단계·시간만, 주제·대사 없음)
- project/ (프로젝트를 골랐을 때만): project.json과 렌더 로그. 주제와 대사가 들어 있다.

보내기 전에 내용을 열어 확인해도 된다. 키 문자열은 [숨김]으로 지웠다.
"""


def bundle(
    settings: Settings,
    setup_problems: list[str],
    project_dir: Path | None = None,
) -> bytes:
    """문제 보고용 zip을 만든다."""
    secrets = secret_values(settings)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README)
        env = environment(settings, setup_problems)
        z.writestr("environment.json", json.dumps(env, ensure_ascii=False, indent=2))

        def add(path: Path, arcname: str) -> None:
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                z.writestr(arcname, scrub(text, secrets))

        for f in sorted(log_dir(settings).glob("app.log*")):
            add(f, f"logs/{f.name}")
        add(settings.data_dir / "metrics.jsonl", "metrics.jsonl")
        if project_dir is not None:
            add(project_dir / "project.json", "project/project.json")
            add(project_dir / "render" / "render.log", "project/render.log")
            add(project_dir / "render" / "work" / "graph.txt", "project/graph.txt")
    return buf.getvalue()
