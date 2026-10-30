"""환경 설정. 모든 엔진 선택은 여기 값만 바꿔서 전환한다 (PROJECT_PROMPT §2-2)."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SHORTFORGE_ROOT = Path(__file__).resolve().parents[2]  # shortforge/
# stock = 무료 사진 기본 소스(Pixabay). Pexels는 신규 키 발급이 중단돼 명시할 때만 쓴다
# video: 사람이 나오지 않는 장면은 Pixabay 무료 동영상 (adapters/image/pixabay_video.py)
IMAGE_SOURCES = {"upload", "cloudflare", "stock", "pixabay", "pexels", "comfyui", "video"}
ENV_FILE = SHORTFORGE_ROOT / ".env"
# LLM 작업 이름 (adapters/fake.FakeLLM의 _<task> 메서드와 같다)
LLM_TASKS = {
    "s1_keywords", "s2_relevance", "s3_thumbnails", "s3_factors", "s4_strategy",
    "s4_shorten", "s4_lengthen", "s5_image_prompts", "s5_video_check", "s6_timeline",
}  # fmt: skip


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    youtube_api_key: str = ""
    gemini_api_key: str = ""
    # gemini-2.5-flash는 2026-10 기준 신규 사용자에게 제공되지 않는다(404). 버전 고정 이름을 쓴다
    gemini_model: str = "gemini-3.8-flash"
    # 가벼운 작업(S1 키워드·S2 관련성·S6 연출)용. 무료 일일 한도가 모델마다 따로라 처리량이 는다
    gemini_model_light: str = "gemini-3.5-flash-lite"
    # 주 모델(S3 요인·S4 전략)의 사고 수준: minimal|low|medium|high, 비우면 모델 기본값.
    # 낮을수록 빠르다. 2026-10-19 Gate(scripts/llm_smoke.py) 3회 통과: low는 S3 요인 12.7→6초,
    # S4 전략 1회 17~32→8~10초. 대신 재생성 때 글자 수 제한을 덜 지킨다
    gemini_thinking_level: str = "low"

    llm_mode: Literal["gemini", "ollama"] = "gemini"

    # 고급 모드 (D13, 선택·유료): 사용자 키로 품질이 중요한 작업만 유료 모델에 보낸다.
    # off면 지금과 완전히 같다(비용 ₩0). 하루 예산을 넘거나 실패하면 무료 경로로 돌아간다
    llm_advanced: Literal["off", "anthropic", "openai", "openrouter"] = "off"
    advanced_model: str = ""  # 비우면 제공자 기본값 (app/spend.DEFAULT_MODEL)
    advanced_tasks: str = "s3_factors,s4_strategy"
    advanced_effort: Literal["low", "medium", "high"] = "medium"
    advanced_daily_budget_usd: float = Field(default=1.0, ge=0.0, le=100.0)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"

    # 이미지 소스를 시도 순서대로:
    #   upload(생성 안 함) | cloudflare | stock(=pixabay) | pexels | comfyui
    # 예) "cloudflare,stock" — Cloudflare 생성, 실패·한도 초과면 Pixabay 사진 (D12)
    image_mode: str = "upload"
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    cloudflare_image_model: str = "@cf/black-forest-labs/flux-2-klein-4b"
    cloudflare_daily_neurons: int = 10_000
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    comfyui_url: str = ""
    comfyui_workflow: Path | None = None  # 비우면 기본 SDXL 템플릿

    tts_mode: Literal["edge", "melo"] = "edge"
    tts_voice: str = "ko-KR-SunHiNeural"

    # S6: LLM이 장면 연출(모션·전환·자막 스타일)을 고른다. False면 규칙 기반만
    s6_use_llm: bool = True
    # S6 배경음악: auto면 내용에 맞는 분위기를 골라 로컬에서 합성한다(₩0). off면 음악 없이
    bgm_mode: Literal["auto", "off"] = "auto"

    # S7 렌더 (FFmpeg)
    render_preset: str = "veryfast"  # libx264 preset. Step 2 측정으로 결정
    render_workers: int = 0  # 0 = CPU 코어 수의 절반
    # 다듬는 동안 바뀐 장면 클립을 뒤에서 미리 만든다(실측 110.9초 → 31.9초). CPU를 쓰므로 기본은 끔
    prerender_clips: bool = False
    # auto = 설치된 글꼴 중 Pretendard → Noto Sans KR → 나눔고딕 → 맑은 고딕 순서로 고른다
    subtitle_font: str = "auto"
    # 렌더 색 보정: film(대비·따뜻한 톤·비네팅·약한 그레인) | clean(대비만 살짝) | off
    render_grade: Literal["film", "clean", "off"] = "film"
    # 엔딩 카드에 넣을 채널 이름 (비우면 엔딩 카드 없음). 설정 화면에서 바꾼다
    brand_name: str = ""

    youtube_daily_unit_limit: int = 8000

    # 웹 UI (Next.js 개발 서버)
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    # 개발용: LLM만 Fake로 (Gemini 키 없이 UI 개발)
    dev_fake_llm: bool = False
    # 화면 자동 테스트(CI)용: 모든 어댑터를 Fake로 (키·FFmpeg·네트워크 없이 7단계 끝까지)
    dev_fake_all: bool = False
    ref_max_duration_sec: int = 60

    data_dir: Path = Path("./data")

    @field_validator("data_dir")
    @classmethod
    def _anchor_data_dir(cls, v: Path) -> Path:
        """상대 경로는 실행 위치가 아니라 shortforge/ 기준 (data/는 git 제외 대상)."""
        return v if v.is_absolute() else (SHORTFORGE_ROOT / v).resolve()

    @field_validator("gemini_thinking_level")
    @classmethod
    def _check_thinking_level(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"", "minimal", "low", "medium", "high"}:
            raise ValueError("GEMINI_THINKING_LEVEL: minimal·low·medium·high 또는 빈 값")
        return v

    @field_validator("advanced_tasks")
    @classmethod
    def _check_advanced_tasks(cls, v: str) -> str:
        tokens = [t.strip() for t in v.split(",") if t.strip()]
        bad = set(tokens) - LLM_TASKS
        if bad:
            raise ValueError(f"ADVANCED_TASKS에 알 수 없는 작업: {', '.join(sorted(bad))}")
        return ",".join(tokens)

    @property
    def advanced_task_set(self) -> set[str]:
        return {t for t in self.advanced_tasks.split(",") if t}

    @field_validator("image_mode")
    @classmethod
    def _check_image_mode(cls, v: str) -> str:
        tokens = [t.strip() for t in v.split(",") if t.strip()]
        bad = set(tokens) - IMAGE_SOURCES
        if not tokens or bad:
            shown = ", ".join(sorted(bad)) or "(비어 있음)"
            raise ValueError(f"IMAGE_MODE에 알 수 없는 값: {shown}")
        return ",".join(tokens)

    @property
    def image_sources(self) -> list[str]:
        return [t for t in self.image_mode.split(",") if t != "upload"]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "shortforge.db"


settings = Settings()
