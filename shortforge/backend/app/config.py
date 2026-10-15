"""환경 설정. 모든 엔진 선택은 여기 값만 바꿔서 전환한다 (PROJECT_PROMPT §2-2)."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# shortforge/.env (backend/의 상위 디렉터리)
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    youtube_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    llm_mode: Literal["gemini", "ollama"] = "gemini"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"

    image_mode: Literal["upload", "comfyui"] = "upload"
    comfyui_url: str = ""

    tts_mode: Literal["edge", "melo"] = "edge"
    tts_voice: str = "ko-KR-SunHiNeural"

    youtube_daily_unit_limit: int = 8000
    ref_max_duration_sec: int = 60

    data_dir: Path = Path("./data")


settings = Settings()
