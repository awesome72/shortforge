"""어댑터 인터페이스. 모든 외부 모델·API는 이 뒤에 둔다 (PROJECT_PROMPT §2-2).

엔진 교체(Gemini↔Ollama, FFmpeg↔Remotion 등)는 registry 설정만 바꿔서 한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app.schemas.project import Timeline

T = TypeVar("T", bound=BaseModel)

ProgressFn = Callable[[str, float], Awaitable[None]]  # (단계 이름, 0.0~1.0)


# ── LLM ─────────────────────────────────────────────────


class LLMAdapter(ABC):
    @abstractmethod
    async def generate_json(self, task: str, system: str, user: str, schema: type[T]) -> T:
        """schema에 맞는 JSON을 생성해 검증된 모델로 돌려준다. task는 로깅·캐시용 이름."""


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


class ImageAdapter(ABC):
    @abstractmethod
    async def generate(self, prompt: str, negative: str, seed: int, out_path: Path) -> Path | None:
        """이미지를 만들면 경로, 생성하지 않는 모드(upload)면 None."""


# ── Video (렌더러) ──────────────────────────────────────


@dataclass
class RenderResult:
    path: Path
    srt: Path
    duration_sec: float
    log: Path


class VideoAdapter(ABC):
    @abstractmethod
    async def render(
        self, timeline: Timeline, project_dir: Path, progress: ProgressFn
    ) -> RenderResult: ...


# ── 묶음 ────────────────────────────────────────────────


@dataclass
class Adapters:
    llm: LLMAdapter
    youtube: YouTubeAdapter
    tts: TTSAdapter
    image: ImageAdapter
    video: VideoAdapter
