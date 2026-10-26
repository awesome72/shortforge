"""어댑터 인터페이스. 모든 외부 모델·API는 이 뒤에 둔다 (PROJECT_PROMPT §2-2).

엔진 교체(Gemini↔Ollama, FFmpeg↔Remotion 등)는 registry 설정만 바꿔서 한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel

from app.schemas.project import Timeline

T = TypeVar("T", bound=BaseModel)

ProgressFn = Callable[[str, float], Awaitable[None]]  # (단계 이름, 0.0~1.0)


# ── LLM ─────────────────────────────────────────────────


class LLMAdapter(ABC):
    supports_images = False  # 공개 이미지 URL을 함께 볼 수 있는가 (F-3.3 썸네일 분석)

    @abstractmethod
    async def generate_json(
        self, task: str, system: str, user: str, schema: type[T], *, images: Sequence[str] = ()
    ) -> T:
        """schema에 맞는 JSON을 생성해 검증된 모델로 돌려준다. task는 로깅·캐시용 이름.

        images는 공개 이미지 URL이다. 내려받지 않고 모델 쪽에서 읽게 넘긴다(supports_images일 때만).
        """


# ── YouTube ─────────────────────────────────────────────


class VideoInfo(BaseModel):
    video_id: str
    title: str
    description: str = ""
    tags: list[str] = []
    channel_id: str
    views: int
    likes: int
    comments: int
    duration_sec: int
    published_at: datetime
    thumbnail_url: str


class ChannelInfo(BaseModel):
    channel_id: str
    subs: int | None  # hiddenSubscriberCount면 None


class YouTubeAdapter(ABC):
    @abstractmethod
    async def search(
        self, keyword: str, region: str, lang: str, published_after: datetime, max_results: int
    ) -> list[str]:
        """search.list (100 units). 영상 ID 목록."""

    @abstractmethod
    async def videos(self, ids: list[str]) -> list[VideoInfo]:
        """videos.list (1 unit / 50개)."""

    @abstractmethod
    async def channels(self, ids: list[str]) -> list[ChannelInfo]:
        """channels.list (1 unit / 50개)."""

    @abstractmethod
    async def top_comments(self, video_id: str, max_results: int = 100) -> list[str]:
        """commentThreads.list order=relevance (1 unit)."""


# ── TTS ─────────────────────────────────────────────────


@dataclass
class TTSResult:
    path: Path
    duration_sec: float
    words_path: Path | None = None


class TTSAdapter(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice: str, rate: str, out_path: Path) -> TTSResult: ...


# ── Image ───────────────────────────────────────────────


@dataclass
class ImageRequest:
    prompt: str  # 생성용 프롬프트 (가능하면 영어)
    negative: str
    seed: int
    out_path: Path  # 확장자는 어댑터가 실제 형식에 맞게 바꿀 수 있다
    query: str = ""  # 사진 검색용 짧은 키워드 (stock)


@dataclass
class ImageResult:
    path: Path
    source: Literal["generated", "stock"]
    provider: str  # 예: "cloudflare:flux-2-klein-4b", "pexels"
    credit: str | None = None  # 출처 표기 (사진 작가 등)


class ImageQuotaExceeded(RuntimeError):
    """무료 한도를 다 썼다 — 체인은 다음 이미지 소스로 넘어간다."""


class ImageAdapter(ABC):
    # S5가 장면 묘사를 영문 이미지 프롬프트·검색어로 바꿔 줄지 (생성·검색 어댑터만 True)
    wants_english_prompts: bool = False

    @abstractmethod
    async def generate(self, req: ImageRequest) -> ImageResult | None:
        """이미지를 만들거나 찾으면 결과, 만들지 않는 모드(upload)면 None."""


# ── Video (렌더러) ──────────────────────────────────────


@dataclass
class RenderResult:
    path: Path
    srt: Path
    duration_sec: float
    log: Path
    # 내보내기 전 점검용 측정값. 측정하지 못하면 None·빈 목록
    loudness_lufs: float | None = None
    silences: list[tuple[float, float]] = field(default_factory=list)  # (시작 초, 길이 초)
    wide_captions: list[str] = field(default_factory=list)  # 화면 폭을 넘어 한 줄 더 접힐 자막


class VideoAdapter(ABC):
    @abstractmethod
    async def render(
        self, timeline: Timeline, project_dir: Path, progress: ProgressFn
    ) -> RenderResult: ...

    @abstractmethod
    async def make_bgm(self, out: Path, mood: str, duration: float, seed: int) -> Path:
        """분위기에 맞는 배경음악 파일을 out에 만든다 (이미 있으면 그대로 쓴다)."""

    @abstractmethod
    async def make_cover(
        self, image: Path, title: str, out: Path, width: int, height: int, project_dir: Path
    ) -> Path:
        """장면 이미지에 제목을 얹은 세로 커버(썸네일) 한 장을 out에 만든다."""


# ── 묶음 ────────────────────────────────────────────────


@dataclass
class Adapters:
    llm: LLMAdapter
    youtube: YouTubeAdapter
    tts: TTSAdapter
    image: ImageAdapter
    video: VideoAdapter
