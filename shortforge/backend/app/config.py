"""환경 설정. 모든 엔진 선택은 여기 값만 바꿔서 전환한다 (PROJECT_PROMPT §2-2)."""

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SHORTFORGE_ROOT = Path(__file__).resolve().parents[2]  # shortforge/
ENV_FILE = SHORTFORGE_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    youtube_api_key: str = ""
    gemini_api_key: str = ""
    # gemini-2.5-flash는 2026-10 기준 신규 사용자에게 제공되지 않는다(404). 버전 고정 이름을 쓴다
    gemini_model: str = "gemini-3.8-flash"

    llm_mode: Literal["gemini", "ollama"] = "gemini"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"

    image_mode: Literal["upload", "comfyui"] = "upload"
    comfyui_url: str = ""

    tts_mode: Literal["edge", "melo"] = "edge"
    tts_voice: str = "ko-KR-SunHiNeural"

    # S7 렌더 (FFmpeg)
    render_preset: str = "veryfast"  # libx264 preset. Step 2 측정으로 결정
    render_workers: int = 0  # 0 = CPU 코어 수의 절반
    subtitle_font: str = "Malgun Gothic"

    youtube_daily_unit_limit: int = 8000
    ref_max_duration_sec: int = 60

    data_dir: Path = Path("./data")

    @field_validator("data_dir")
    @classmethod
    def _anchor_data_dir(cls, v: Path) -> Path:
        """상대 경로는 실행 위치가 아니라 shortforge/ 기준 (data/는 git 제외 대상)."""
        return v if v.is_absolute() else (SHORTFORGE_ROOT / v).resolve()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "shortforge.db"


settings = Settings()
