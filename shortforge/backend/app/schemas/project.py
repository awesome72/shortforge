"""Project JSON 계약 (PROJECT_PROMPT §5~6).

Project 하나가 단일 진실 원천이다. 각 단계는 자기 입력 키를 읽고 출력 키 하나만 쓴다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

StepId = Literal["s1", "s2", "s3", "s4", "s5", "s6", "s7"]
STEP_IDS: tuple[StepId, ...] = ("s1", "s2", "s3", "s4", "s5", "s6", "s7")


def utcnow() -> datetime:
    return datetime.now(UTC)


class StepState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    STALE = "stale"
    ERROR = "error"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ── S1 입력 ──────────────────────────────────────────────


class Input(Model):
    topic: str = Field(min_length=1)
    audience: str = ""
    tone: Literal["empathetic", "informative", "humor"] = "empathetic"
    duration_sec: Literal[15, 30, 60] = 30
    aspect: Literal["9:16"] = "9:16"
    lang: str = "ko"
    region: str = "KR"
    user_media: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list, max_length=5)
    # 장면 그림체. auto면 4단계 스타일을 따른다 (바꾸면 5단계부터 다시)
    visual_style: Literal["auto", "photo", "cinematic", "illustration", "watercolor"] = "auto"
    # 내레이션 목소리. auto면 타깃에 맞춰 고르고, 그림 속 주인공 성별도 이 목소리를 따른다
    voice: Literal["auto", "female", "male"] = "auto"


# ── S2 레퍼런스 ──────────────────────────────────────────


class Ref(Model):
    video_id: str
    title: str
    channel_id: str
    subs: int | None  # None = 숨김 구독자 수
    views: int
    likes: int
    comments: int
    duration_sec: int
    published_at: datetime
    ratio_views_per_sub: float | None
    views_per_day: float
    like_rate: float
    score: float
    thumbnail_url: str
    relevant: bool | None = None  # S2 LLM 관련성 판정 (None = 판정하지 않음)
    selected: bool = False
    fetched_at: datetime = Field(default_factory=utcnow)


# ── S3 성공 요인 ─────────────────────────────────────────

FactorName = Literal["hook", "title", "length", "empathy", "visual", "timing", "cta"]


class Factor(Model):
    name: FactorName
    finding: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)  # "video_id:field"
    confidence: Literal["confirmed", "estimated"]

    @field_validator("evidence")
    @classmethod
    def _evidence_format(cls, v: list[str]) -> list[str]:
        for e in v:
            vid, _, field = e.partition(":")
            if not vid or not field:
                raise ValueError(f"evidence는 'video_id:field' 형식이어야 한다: {e!r}")
        return v


# ── S4 전략 ──────────────────────────────────────────────


class Scene(Model):
    id: str = Field(pattern=r"^S\d+$")
    role: Literal["hook", "problem", "method", "payoff", "cta"]
    start: float = Field(ge=0)
    end: float
    line: str
    visual: str
    factor_refs: list[FactorName] = Field(default_factory=list)

    @model_validator(mode="after")
    def _end_after_start(self) -> Scene:
        if self.end <= self.start:
            raise ValueError(f"{self.id}: end({self.end})는 start({self.start})보다 커야 한다")
        return self


class Strategy(Model):
    titles: list[str] = Field(min_length=2, max_length=2)
    post_time_hint: str
    differentiator: str
    style_seed: str
    scenes: list[Scene] = Field(min_length=5, max_length=7)


# ── S5 자산 ──────────────────────────────────────────────


class ImageAsset(Model):
    prompt: str
    negative: str = ""
    seed: int = 0
    source: Literal["generated", "user", "stock"] = "generated"
    path: str | None = None
    query: str = ""  # 사진 검색 키워드 (stock)
    provider: str | None = None  # 이미지를 만든·찾은 서비스
    credit: str | None = None  # 출처 표기 (사진 작가 등)
    basis: str | None = None  # 이 이미지를 정한 장면 묘사+스타일 시드. S5 재실행 때 재사용 판단
    # 생성 프롬프트 규칙 버전 (app/image_prompt.PROMPT_REV). 낮으면 S5 재실행 때 새로 만든다
    rev: int = 0


class VoiceAsset(Model):
    text: str
    voice: str
    rate: str = "+0%"
    path: str | None = None
    duration_sec: float | None = None  # 음성 파일 길이
    words_path: str | None = None  # WordBoundary 타이밍 (SRT 생성용)
    # 끝의 조용한 부분을 뺀 말 길이. 장면 길이는 이것으로 잡는다 (예전 프로젝트는 없음 → 파일 길이)
    speech_sec: float | None = None

    @property
    def length(self) -> float | None:
        return self.speech_sec if self.speech_sec is not None else self.duration_sec


class Asset(Model):
    scene_id: str
    image: ImageAsset
    voice: VoiceAsset


# ── S6 타임라인 ──────────────────────────────────────────


class Canvas(Model):
    w: int = 1080
    h: int = 1920
    fps: int = 30


class AudioMix(Model):
    bgm: str | None = None
    bgm_gain_db: float = -18
    duck_db: float = -12
    # 배경음악 출처: generated(분위기별 합성, app/music.py) | user(직접 올린 파일).
    # None이면 음악 없음
    source: Literal["generated", "user"] | None = None
    mood: str | None = None  # app.music.MOOD_LABEL의 키
    variant: int = 0  # "다른 곡"을 누를 때마다 1씩 올라 합성 seed가 바뀐다
    locked: bool = False  # 사용자가 직접 고른 음악(끈 상태 포함). S6를 다시 실행해도 유지한다


class Motion(Model):
    type: Literal["zoom_in", "zoom_out", "pan_left", "pan_right", "static"] = "zoom_in"
    amount: float = Field(default=0.12, ge=0, le=0.5)


class Transition(Model):
    type: Literal["cut", "fade", "slide"] = "cut"
    dur: float = Field(default=0.2, ge=0, le=1.0)


class Caption(Model):
    text: str
    style: Literal["hook_bold", "body", "emphasis"] = "body"


# 마지막 장면에 더 두는 여백(초). 렌더가 끝 0.5초를 페이드로 닫아, 장면 길이를 말 길이로 잡은 뒤로는
# 마지막 말이 끝나자마자 어두워지고 끝음이 깎였다. S4 대사 분량·S5 길이 맞추기도 이 값을 뺀다
LAST_SCENE_EXTRA_PAD = 0.4


class TimelineScene(Model):
    id: str
    image: str
    voice: str
    duration: float | Literal["auto"] = "auto"
    pad: float = Field(default=0.2, ge=0)
    motion: Motion = Field(default_factory=Motion)
    transition: Transition = Field(default_factory=Transition)
    caption: Caption
    gen_video: bool = False


class Subtitles(Model):
    source: Literal["tts", "whisper"] = "tts"
    burn_in: bool = True
    max_chars_per_line: int = 14


class Timeline(Model):
    canvas: Canvas = Field(default_factory=Canvas)
    audio: AudioMix = Field(default_factory=AudioMix)
    scenes: list[TimelineScene] = Field(min_length=1)
    subtitles: Subtitles = Field(default_factory=Subtitles)


# ── S7 렌더 ──────────────────────────────────────────────


class RenderCheck(Model):
    """내보내기 전 자동 점검 한 항목 (S7이 렌더 직후 측정)."""

    id: Literal["duration", "loudness", "silence", "caption_width"]
    ok: bool
    detail: str


class Render(Model):
    path: str
    srt: str
    duration_sec: float
    log: str
    # 렌더 방식 버전 (app/steps/s7_render.RENDER_QUALITY). 0은 이 값을 남기기 전의 렌더
    quality: int = 0
    checks: list[RenderCheck] = Field(default_factory=list)


# ── Project ──────────────────────────────────────────────


def _initial_status() -> dict[StepId, StepState]:
    return dict.fromkeys(STEP_IDS, StepState.IDLE)


class StepLLMUsage(Model):
    """이 단계의 LLM 요청 요약 (화면 표시용). 고급 모드가 실제로 일했는지 보여 준다."""

    models: list[str] = Field(default_factory=list)  # 처리한 모델 (요청 순서, 중복 없이)
    providers: list[str] = Field(default_factory=list)  # gemini | anthropic | openai | openrouter
    calls: int = 0
    usd: float = 0.0  # 고급 모드(유료) 비용 합계


class Project(Model):
    id: str
    version: int = 0
    parent_id: str | None = None  # A/B 변형이면 원본 프로젝트 ID (F-W6)
    variant: str | None = None  # 변형 표시: "B", "C" … (원본은 None)
    updated_at: datetime = Field(default_factory=utcnow)
    status: dict[StepId, StepState] = Field(default_factory=_initial_status)
    errors: dict[StepId, str] = Field(default_factory=dict)
    warnings: dict[StepId, list[str]] = Field(default_factory=dict)
    llm_usage: dict[StepId, StepLLMUsage] = Field(default_factory=dict)

    input: Input | None = None
    refs: list[Ref] | None = None
    factors: list[Factor] | None = None
    strategy: Strategy | None = None
    assets: list[Asset] | None = None
    timeline: Timeline | None = None
    render: Render | None = None


# 단계가 쓰는 출력 키 (PATCH 허용 대상)
OutputKey = Literal["input", "refs", "factors", "strategy", "assets", "timeline", "render"]
