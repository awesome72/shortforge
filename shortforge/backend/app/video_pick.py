"""무료 동영상 고르기 2단계: 태그 순위 상위 영상의 썸네일을 보고 다시 줄 세운다 (D15).

태그만으로는 "노트북 컴퓨터를 쓰는 사람" 영상처럼 태그에 사람 단어가 없는 영상을 걸러 내지 못했다
(2026-10 실측). 이미지를 볼 수 있는 무료 경량 모델(`s5_video_check`)에 상위 몇 개의 썸네일을 한 번에
넘겨 "장면에 맞는지(0~2)·사람이 보이는지"를 받는다. 썸네일은 내려받지 않고 URL로 넘긴다
(3단계와 같다).
실패하거나 모델이 이미지를 못 보면 태그 순서를 그대로 쓴다.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.adapters.base import LLMAdapter
from app.llm import load_prompt, wrap_untrusted

log = logging.getLogger("app.video_pick")

VISION_TOP = 8  # 썸네일을 볼 영상 수 (요청 1회)
PERSON_PENALTY = 2


class VideoCheck(BaseModel):
    index: int
    fits: int = Field(ge=0, le=2)  # 0: 장면과 다름, 1: 비슷함, 2: 잘 맞음
    person: bool = False  # 사람(얼굴·몸)이 보이는가. 손만 보이면 False


class VideoCheckOut(BaseModel):
    videos: list[VideoCheck]


def thumbnail(hit: dict) -> str:
    videos = hit.get("videos", {})
    for size in ("tiny", "small", "medium"):
        url = (videos.get(size) or {}).get("thumbnail")
        if url:
            return url
    return ""


async def judge(
    llm: LLMAdapter | None, hits: list[dict], scene: str, person_ok: bool
) -> list[dict]:
    """상위 VISION_TOP개를 썸네일로 다시 줄 세운다. 맞지 않는(fits 0) 영상은 뒤로 보낸다.

    person_ok가 거짓(사람이 없어야 하는 장면)이면 사람이 보이는 영상을 감점한다.
    """
    top = [h for h in hits[:VISION_TOP] if thumbnail(h)]
    if llm is None or not llm.supports_images or len(top) < 2:
        return hits
    user = "\n".join(
        [f"scene: {wrap_untrusted(scene)}", f"people_allowed: {str(person_ok).lower()}", ""]
        + [f"{i}: tags {wrap_untrusted(h.get('tags', ''))}" for i, h in enumerate(top)]
    )
    try:
        out = await llm.generate_json(
            "s5_video_check",
            load_prompt("s5_video_check").text,
            user,
            VideoCheckOut,
            images=[thumbnail(h) for h in top],
        )
    except Exception as e:  # noqa: BLE001 - 보조 판정이라 실패해도 태그 순서로 간다
        log.warning("영상 썸네일 판정 실패: %s", type(e).__name__)
        return hits
    score = {
        v.index: v.fits - (PERSON_PENALTY if v.person and not person_ok else 0)
        for v in out.videos
        if 0 <= v.index < len(top)
    }
    # 판정이 빠진 영상은 0점(태그 순서 유지). 같은 점수면 원래 순서
    order = sorted(range(len(top)), key=lambda i: (-score.get(i, 0), i))
    good = [top[i] for i in order if score.get(i, 0) > 0]
    rest = [top[i] for i in order if score.get(i, 0) <= 0]
    seen = {h["id"] for h in top}
    return good + rest + [h for h in hits if h["id"] not in seen]
