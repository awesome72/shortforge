"""결정론적 Fake 어댑터. 외부 호출·파일 생성 없이 파이프라인 전체를 돌리기 위한 것.

테스트와 오프라인 개발에서 쓴다. 출력은 입력이 같으면 항상 같다.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.adapters.base import (
    Adapters,
    ChannelInfo,
    ImageAdapter,
    ImageRequest,
    ImageResult,
    LLMAdapter,
    ProgressFn,
    RenderResult,
    T,
    TTSAdapter,
    TTSResult,
    VideoAdapter,
    VideoInfo,
    YouTubeAdapter,
)
from app.schemas.project import Timeline


def _h(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16)


class FakeLLM(LLMAdapter):
    """task 이름별로 고정 응답을 만든다. calls에 호출 기록을 남긴다."""

    supports_images = True

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.notices: list[str] = []

    def drain_notices(self) -> list[str]:
        out, self.notices = self.notices, []
        return out

    async def generate_json(
        self, task: str, system: str, user: str, schema: type[T], *, images: Sequence[str] = ()
    ) -> T:
        self.calls.append(task)
        self.images = list(images)
        builder = getattr(self, f"_{task}", None)
        if builder is None:
            raise NotImplementedError(f"FakeLLM에 '{task}' 응답이 없다")
        return schema.model_validate(builder(user))

    def _s1_keywords(self, user: str) -> dict:
        return {"keywords": ["퇴근 후 홈트", "10분 운동 변화", "직장인 운동 루틴 shorts"]}

    def _s2_relevance(self, user: str) -> dict:
        """첫 번째 후보만 무관하다고 판정한다 (뒤로 밀려 선택에서 빠져야 한다)."""
        ids = re.findall(r"video_id:\s*(\S+)", user)
        return {"items": [{"video_id": v, "relevant": i != 0} for i, v in enumerate(ids)]}

    def _s3_thumbnails(self, user: str) -> dict:
        ids = re.findall(r"video_id:\s*(\S+)", user)
        return {
            "thumbnails": [
                {"video_id": v, "observation": "큰 노란 글씨로 숫자를 강조, 인물 얼굴 클로즈업"}
                for v in ids
            ]
        }

    def _s3_factors(self, user: str) -> dict:
        ids = re.findall(r"video_id:\s*(\S+)", user) or ["unknown"]
        return {
            "factors": [
                {
                    "name": "title",
                    "finding": "기간 + 숫자 + 변화 구조의 제목",
                    "evidence": [f"{i}:snippet.title" for i in ids[:2]],
                    "confidence": "confirmed",
                },
                {
                    "name": "hook",
                    "finding": "결과를 먼저 보여 주는 훅",
                    "evidence": [f"{ids[0]}:snippet.title"],
                    "confidence": "estimated",
                },
                {
                    "name": "length",
                    "finding": "상위 영상 대부분 20~35초",
                    "evidence": [f"{i}:contentDetails.duration" for i in ids],
                    "confidence": "confirmed",
                },
                *(
                    [
                        {
                            "name": "visual",
                            "finding": "썸네일에 큰 글씨 숫자와 얼굴 클로즈업",
                            "evidence": [f"{ids[0]}:thumbnail"],
                            "confidence": "confirmed",  # S3가 estimated로 낮춰야 한다
                        }
                    ]
                    if "thumbnail:" in user
                    else []
                ),
                {
                    "name": "empathy",
                    "finding": "근거 없는 요인 — 폐기되어야 한다",
                    "evidence": ["not_a_selected_video:snippet.title"],
                    "confidence": "estimated",
                },
            ]
        }

    def _s4_strategy(self, user: str) -> dict:
        lines = [
            ("hook", 0, 2, "3개월 전엔 계단도 숨찼어요"),
            ("problem", 2, 8, "퇴근하면 운동할 힘이 없었죠"),
            ("method", 8, 18, "그래서 딱 10분, 이 세 동작만 했어요"),
            ("payoff", 18, 26, "지금은 아침이 달라졌어요"),
            ("cta", 26, 30, "오늘 10분, 같이 시작해요"),
        ]
        return {
            "titles": [
                "퇴근 후 10분 홈트 3개월, 이렇게 바뀌었다",
                "하루 10분으로 달라진 직장인의 몸",
            ],
            "post_time_hint": "평일 19~21시",
            "differentiator": "본인 실제 기록 삽입",
            "style_seed": "vertical 9:16, natural window light, muted warm palette, 35mm photo",
            "scenes": [
                {
                    "id": f"S{i + 1}",
                    "role": role,
                    "start": s,
                    "end": e,
                    "line": line,
                    "visual": f"{role} 장면",
                    "factor_refs": ["hook"] if role == "hook" else ["title"],
                }
                for i, (role, s, e, line) in enumerate(lines)
            ],
        }

    def _s4_shorten(self, user: str) -> dict:
        """max_chars가 붙은 장면 대사를 그 길이로 자른다."""
        out = []
        for m in re.finditer(r"^(S\d+) role=\w+ max_chars=(\d+) .*?line=(.*)$", user, re.M):
            line = ast.literal_eval(m.group(3))  # repr로 넣은 대사
            out.append({"id": m.group(1), "line": line[: int(m.group(2)) - 1]})
        return {"scenes": out}
        return {"scenes": out}

    def _s5_image_prompts(self, user: str) -> dict:
        ids = re.findall(r"^(S\d+) ", user, flags=re.M)
        return {
            "style": "muted warm palette, soft window light",
            "subject": "a Korean office worker in a grey cardigan",
            "scenes": [
                {"id": sid, "prompt": f"photo of scene {sid}, hands only", "query": f"office {sid}"}
                for sid in ids
            ],
        }

    def _s6_timeline(self, user: str) -> dict:
        ids = re.findall(r"^(S\d+) ", user, flags=re.M)
        motions = ["zoom_in", "pan_right", "static", "zoom_out", "pan_left", "zoom_in", "static"]
        return {
            "scenes": [
                {
                    "id": sid,
                    "motion": {"type": motions[i % len(motions)], "amount": 0.1},
                    "transition": {"type": "slide" if i % 2 else "fade", "dur": 0.3},
                    "caption_style": "hook_bold" if i == 0 else "body",
                }
                for i, sid in enumerate(ids)
            ],
            "mood": "warm",
        }


class FakeYouTube(YouTubeAdapter):
    """키워드마다 영상 8개를 돌려준다. units에 쿼터 사용량을 누적한다."""

    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or datetime(2026, 10, 15, tzinfo=UTC)
        self.units = 0

    async def search(self, keyword, region, lang, published_after, max_results):
        self.units += 100
        return [f"v{_h(keyword) % 1000:03d}{i}" for i in range(min(8, max_results))]

    async def videos(self, ids):
        self.units += -(-len(ids) // 50)
        out = []
        for vid in ids:
            h = _h(vid)
            out.append(
                VideoInfo(
                    video_id=vid,
                    title=f"영상 {vid}",
                    channel_id=f"ch{h % 5}",
                    views=10_000 + h % 2_000_000,
                    likes=100 + h % 50_000,
                    comments=10 + h % 900,
                    duration_sec=15 + h % 70,  # 일부는 60초 초과 → 필터 대상
                    published_at=self.now - timedelta(days=1 + h % 80),
                    thumbnail_url=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                )
            )
        return out

    async def channels(self, ids):
        self.units += -(-len(ids) // 50)
        # ch0은 숨김 구독자 수
        return [
            ChannelInfo(channel_id=c, subs=None if c == "ch0" else 500 + _h(c) % 400_000)
            for c in ids
        ]

    async def top_comments(self, video_id, max_results=100):
        self.units += 1
        return ["나만 그런 게 아니었네", "저도 해볼게요"]


class FakeTTS(TTSAdapter):
    """길이 = (0.3 + 글자당 0.12초) / (1 + rate). 실제 TTS처럼 rate가 빠를수록 짧다."""

    def __init__(self, sec_per_char: float = 0.12) -> None:
        self.sec_per_char = sec_per_char
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, text, voice, rate, out_path):
        self.calls.append((text, rate))
        speed = 1 + int(rate.rstrip("%")) / 100
        return TTSResult(
            path=out_path, duration_sec=round((0.3 + self.sec_per_char * len(text)) / speed, 2)
        )


class FakeImage(ImageAdapter):
    wants_english_prompts = True

    def __init__(self) -> None:
        self.requests: list[ImageRequest] = []

    async def generate(self, req: ImageRequest) -> ImageResult:
        self.requests.append(req)
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        if not req.out_path.exists():  # 같은 파일을 다시 쓰면 Windows 백신 잠금에 걸릴 수 있다
            req.out_path.write_bytes(b"fake")  # S5 재실행의 이미지 재사용은 파일이 있어야 한다
        return ImageResult(path=req.out_path, source="generated", provider="fake")


class FakeVideo(VideoAdapter):
    async def render(self, timeline: Timeline, project_dir: Path, progress: ProgressFn):
        for stage in ("clips", "concat", "audio", "subtitles", "encode"):
            await progress(stage, 1.0)
        out = project_dir / "render"
        total = sum(s.duration for s in timeline.scenes if isinstance(s.duration, float))
        return RenderResult(
            path=out / "final.mp4",
            srt=out / "final.srt",
            duration_sec=total,
            log=out / "render.log",
        )

    async def make_bgm(self, out: Path, mood: str, duration: float, seed: int) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            out.write_bytes(f"fake-bgm {mood} {duration:.0f}s {seed}".encode())
        return out


def fake_adapters() -> Adapters:
    return Adapters(
        llm=FakeLLM(), youtube=FakeYouTube(), tts=FakeTTS(), image=FakeImage(), video=FakeVideo()
    )
