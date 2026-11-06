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


class WorldKeyword(Model):
    """해외 시장 검색어 (번역이 아니라 그 나라 사람이 검색할 말)."""

    lang: str
    keyword: str = Field(min_length=1)


PURPOSE_LABEL = {
    "new_menu": "신메뉴 홍보",
    "promotion": "이벤트 홍보",
    "intro": "가게 소개",
    "notice": "가게 공지",
}


PhotoKind = Literal[
    "menu", "shop", "owner", "other",
    # 매물 홍보 (docs/PLAN_LISTING.md)
    "exterior", "living", "kitchen", "room", "bath", "view", "plan",
]  # fmt: skip
PHOTO_KIND_LABEL: dict[str, str] = {
    "menu": "메뉴·음식",
    "shop": "매장·간판",
    "owner": "사장님·조리 모습",
    "other": "기타",
    "exterior": "외관·단지",
    "living": "거실",
    "kitchen": "주방",
    "room": "방",
    "bath": "욕실",
    "view": "창밖·전망",
    "plan": "평면도",
}

PROPERTY_LABEL = {
    "apartment": "아파트",
    "officetel": "오피스텔",
    "villa": "빌라",
    "oneroom": "원룸",
}
DEAL_LABEL = {"sale": "매매", "jeonse": "전세", "monthly": "월세"}


class BusinessBrief(Model):
    """소상공인 모드의 입력. 혜택과 끝맺음 대사는 이 값을 그대로 쓴다 (app/modes.py)."""

    shop_name: str = Field(min_length=1, max_length=40)
    category: Literal["restaurant"] = "restaurant"  # 첫 업종은 음식점
    area: str = Field(default="", max_length=40)
    purpose: Literal["new_menu", "promotion", "intro", "notice"] = "new_menu"
    product: str = Field(default="", max_length=80)
    offer: str = Field(default="", max_length=80)
    period: str = Field(default="", max_length=40)
    action: str = Field(default="", max_length=40)  # 손님이 할 일. 마지막 대사로 그대로 나간다
    pride: str = Field(default="", max_length=80)  # 사장님이 직접 적은 자랑. 대본의 유일한 근거

    @model_validator(mode="after")
    def _promotion_needs_offer(self) -> BusinessBrief:
        if self.purpose == "promotion" and not self.offer.strip():
            raise ValueError("할인·이벤트 영상에는 혜택을 적어 주세요")
        return self


class ListingBrief(Model):
    """매물 홍보 모드의 입력. 공인중개사법 제18조의2의 명시 항목을 받고, 가격·끝맺음 대사와
    영상 끝 매물 정보 카드는 이 값을 그대로 쓴다 (AI가 쓰지 않는다, app/modes.py).

    법은 중개보조원 정보를 넣지 못하게 해 그 칸은 두지 않는다. 중개사무소 정보는 data/offices.json에
    저장해 다시 쓰고, 프로젝트를 만들 때 여기에 복사한다.
    """

    # 중개사무소·개업공인중개사 (명시 의무)
    office_name: str = Field(min_length=1, max_length=40)
    office_address: str = Field(min_length=1, max_length=80)
    office_phone: str = Field(min_length=1, max_length=20)
    agent_name: str = Field(min_length=1, max_length=20)
    reg_no: str = Field(min_length=1, max_length=30)  # 중개사무소 등록번호 (명시 항목)
    # 중개대상물 (명시 의무, 주거용 건축물)
    prop_type: Literal["apartment", "officetel", "villa", "oneroom"] = "apartment"
    deal: Literal["sale", "jeonse", "monthly"] = "jeonse"
    price: str = Field(min_length=1, max_length=40)  # 의뢰받은 가격 그대로 (예: 3억 2천만원)
    location: str = Field(min_length=1, max_length=60)  # 공개할 소재지 (예: 부천시 상동)
    complex_name: str = Field(default="", max_length=40)  # 단지·건물 이름 (선택)
    area: str = Field(min_length=1, max_length=30)  # 공부상 전용면적 (예: 전용 84.9㎡)
    floor: str = Field(min_length=1, max_length=20)  # 해당 층 / 총 층수
    direction: str = Field(min_length=1, max_length=20)  # 방향 (기준 포함, 예: 거실 기준 남향)
    rooms: str = Field(min_length=1, max_length=20)  # 방·욕실 수
    approved: str = Field(min_length=1, max_length=20)  # 사용승인일
    move_in: str = Field(min_length=1, max_length=20)  # 입주 가능일
    parking: str = Field(min_length=1, max_length=20)  # 주차 대수
    maint_fee: str = Field(min_length=1, max_length=40)  # 관리비 (최근 평균)
    # 대본의 근거 (중개사가 직접 쓴 것만)
    highlights: str = Field(default="", max_length=120)
    nearby: str = Field(default="", max_length=80)  # 주변 정보. 거리는 도보 거리·시간으로
    action: str = Field(default="", max_length=40)  # 손님이 할 일. 마지막 대사로 그대로 나간다


class Input(Model):
    topic: str = Field(min_length=1)
    audience: str = ""
    tone: Literal["empathetic", "informative", "humor"] = "empathetic"
    duration_sec: Literal[15, 30, 60] = 30
    aspect: Literal["9:16"] = "9:16"
    lang: str = "ko"
    region: str = "KR"
    user_media: list[str] = Field(default_factory=list)
    # 사진 종류(사장님이 고른다, AI가 읽지 않는다). 가게 대본이 없는 사진을 전제하지 않게 한다
    media_kinds: dict[str, PhotoKind] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list, max_length=5)
    world_keywords: list[WorldKeyword] = Field(default_factory=list)  # 해외 시장 검색어 (S1)
    world_topic: str = ""  # world_keywords를 만든 주제. 주제가 바뀌면 다시 만든다
    # 자동 키워드와 그때의 주제. 주제가 바뀌었고 키워드를 고치지 않았으면 다시 만든다
    # (2026-11-03: 주제를 '식당'으로 고쳐도 예전 키워드로 2단계가 13번 연달아 실패했다)
    keywords_topic: str = ""
    keywords_auto: list[str] = Field(default_factory=list)
    # 참고 영상을 찾지 못한 검색어. '검색어 새로 만들기'가 넘기고 S1이 피한다
    keywords_failed: list[str] = Field(default_factory=list, max_length=20)
    concept_pick: str = ""  # 사용자가 고른 기획 컨셉 (Concept.angle). 비면 점수 1위
    # 장면 그림체. auto면 4단계 스타일을 따른다 (바꾸면 5단계부터 다시)
    visual_style: Literal["auto", "photo", "cinematic", "illustration", "watercolor"] = "auto"
    # 프로젝트 모드 (D21). 만든 뒤에는 바꾸지 않는다. 차이는 app/modes.py에 모은다
    mode: Literal["hobby", "business", "listing"] = "hobby"
    business: BusinessBrief | None = None
    listing: ListingBrief | None = None  # 매물 홍보 모드 (docs/PLAN_LISTING.md)
    # 내레이션 목소리. auto면 타깃에 맞춰 고르고, 그림 속 주인공 성별도 이 목소리를 따른다
    voice: Literal["auto", "female", "male"] = "auto"

    @model_validator(mode="before")
    @classmethod
    def _business_topic(cls, data):
        """소상공인 모드는 주제를 가게 정보로 만든다 (검색·기획이 그대로 주제를 쓴다)."""
        if not isinstance(data, dict) or data.get("mode") not in ("business", "listing"):
            return data
        if str(data.get("topic") or "").strip():
            return data
        if data.get("mode") == "listing":
            lb = data.get("listing")
            lb = lb.model_dump() if isinstance(lb, ListingBrief) else lb
            if not isinstance(lb, dict):
                raise ValueError("매물 홍보에는 매물 정보가 필요하다")
            words = [
                lb.get("location"),
                lb.get("complex_name"),
                PROPERTY_LABEL.get(str(lb.get("prop_type") or "apartment"), ""),
                DEAL_LABEL.get(str(lb.get("deal") or "jeonse"), ""),
                "매물 소개",
            ]
            return {**data, "topic": " ".join(str(w) for w in words if w)}
        b = data.get("business")
        b = b.model_dump() if isinstance(b, BusinessBrief) else b
        if not isinstance(b, dict):
            raise ValueError("소상공인 모드에는 가게 정보가 필요하다")
        purpose = PURPOSE_LABEL.get(str(b.get("purpose") or "new_menu"), "")
        words = [b.get("area"), b.get("shop_name"), b.get("product"), purpose]
        return {**data, "topic": " ".join(str(w) for w in words if w)}

    @model_validator(mode="after")
    def _business_needs_brief(self) -> Input:
        if self.mode == "business" and self.business is None:
            raise ValueError("소상공인 모드에는 가게 정보가 필요하다")
        if self.mode == "listing" and self.listing is None:
            raise ValueError("매물 홍보에는 매물 정보가 필요하다")
        return self


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
    market: str = ""  # 해외 시장 지역 코드 (US·JP…). 비면 입력의 지역
    title_ko: str | None = None  # 해외 영상 제목의 한국어 번역 (S2 관련성 판정과 함께 받는다)
    selected: bool = False
    fetched_at: datetime = Field(default_factory=utcnow)


# ── S3 성공 요인 ─────────────────────────────────────────

# format = 포맷 패턴 카드 (따라 쓸 수 있는 영상 공식)
FactorName = Literal["hook", "title", "length", "empathy", "visual", "timing", "cta", "format"]


# S3 LLM 응답. 시장 비교(scope)는 넣지 않는다: 코드가 근거 영상으로 계산하고, 빈 문자열 enum은
# Gemini 스키마에서 거절될 수 있다 (클래스 설명문은 LLM 스키마에 실려 나가므로 주석으로 둔다)
class FactorDraft(Model):
    name: FactorName
    finding: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)  # "video_id:field"
    confidence: Literal["confirmed", "estimated"]
    # 포맷 패턴 카드(name="format")만 쓴다
    hook_type: str = ""  # 훅 방식 (반전·질문·숫자 등)
    structure: str = ""  # 전개 방식 (전후 비교·리스트·실험 등)
    emotion: str = ""  # 자극하는 감정
    ending: str = ""  # 결말 방식

    @field_validator("evidence")
    @classmethod
    def _evidence_format(cls, v: list[str]) -> list[str]:
        for e in v:
            vid, _, field = e.partition(":")
            if not vid or not field:
                raise ValueError(f"evidence는 'video_id:field' 형식이어야 한다: {e!r}")
        return v


class Factor(FactorDraft):
    # 포맷 패턴 카드의 근거 영상이 어느 시장에 있나 (S3가 계산한다): 공통·해외에서만·한국에서만
    scope: Literal["", "shared", "overseas", "local"] = ""


# ── S4 전략 ──────────────────────────────────────────────


class Scene(Model):
    id: str = Field(pattern=r"^S\d+$")
    role: Literal["hook", "problem", "method", "twist", "payoff", "reveal", "offer", "cta"]
    start: float = Field(ge=0)
    end: float
    line: str
    visual: str
    factor_refs: list[FactorName] = Field(default_factory=list)
    device: str = ""  # 끝까지 보게 하는 장치: open_loop·rehook·loop_end (없으면 빈 값)

    @model_validator(mode="after")
    def _end_after_start(self) -> Scene:
        if self.end <= self.start:
            raise ValueError(f"{self.id}: end({self.end})는 start({self.start})보다 커야 한다")
        return self


class Concept(Model):
    angle: str  # 이번 영상의 아이디어 한 문장
    formula: str = ""  # 어떤 영상 공식을 쓰는가
    hook: str  # 첫 대사
    twist: str = ""  # 뒤집는 지점
    open_loop: str = ""  # 끝까지 미뤄 둘 궁금증
    ending: str = ""  # 마지막 대사 방향
    score: int = 0  # 코드가 합산한 점수


# S4 LLM 응답. 컨셉은 코드가 붙인다 (클래스 설명문은 LLM 스키마에 실려 나가므로 주석으로 둔다)
class StrategyDraft(Model):
    titles: list[str] = Field(min_length=2, max_length=2)
    post_time_hint: str
    differentiator: str
    style_seed: str
    scenes: list[Scene] = Field(min_length=5, max_length=7)


class Strategy(StrategyDraft):
    concept: Concept | None = None  # 고른 컨셉 (예전 프로젝트는 없음)
    other_concepts: list[Concept] = Field(default_factory=list)  # 고르지 않은 컨셉
    concept_basis: str = ""  # 컨셉을 만든 입력의 지문. 같을 때만 지난 후보를 다시 쓴다


# ── S5 자산 ──────────────────────────────────────────────


class ImageCheck(Model):
    """AI 그림 점검 결과 (app/image_check). path가 지금 그림과 같을 때만 유효하다."""

    path: str
    issues: list[Literal["text", "distorted", "other_person"]] = Field(default_factory=list)


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
    # 그림을 움직여 만든 영상(D19)이면 원래 그림. 되돌릴 때 쓰고, 원본의 출처도 여기 남는다
    still: ImageAsset | None = None
    still_motion: Motion | None = None  # 영상으로 바꾸기 전 그 장면의 움직임 (되돌릴 때 쓴다)
    check: ImageCheck | None = None  # 그림 점검 (표시만, 그림이 바뀌면 path가 달라 무시된다)


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
    # 연출 LLM이 본 대사·장면의 지문 (s6_timeline.direction_basis). 같으면 다시 묻지 않는다
    direction_basis: str = ""
    # 그때 연출 LLM이 고른 분위기. audio.mood는 사용자가 바꿀 수 있어 따로 둔다
    direction_mood: str | None = None


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
    error_kinds: dict[StepId, str] = Field(default_factory=dict)  # app.failure, 화면 안내용
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
