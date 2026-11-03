"""AI가 만든 장면 그림 점검 (표시만 한다).

FLUX가 장면마다 가짜 글자·간판을 그리거나(2026-10-21, 11-03 실측 10장 중 2장) 손가락이 일그러지고,
장면마다 다른 사람이 나오는 일(PROMPT_REV 3→5)이 있었다. 한 영상의 생성 그림을 이미지를 볼 수 있는
경량 LLM에 한 번에 보여 문제를 표시하고, 바꿀지는 사용자가 정한다('다른 그림').
사용자가 올린 사진은 보내지 않는다(사진 AI 판독이 아니다). 실패하면 아무것도 표시하지 않는다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from app.adapters.base import LLMAdapter
from app.llm import load_prompt
from app.media import is_video_path
from app.schemas.project import Asset, ImageCheck

log = logging.getLogger(__name__)

MAX_IMAGES = 8
ISSUE_LABEL = {
    "text": "글자가 보여요",
    "distorted": "모양이 어색해요",
    "other_person": "다른 사람 같아요",
}


class _Item(BaseModel):
    index: int
    text: bool = False
    distorted: bool = False
    other_person: bool = False


class _Result(BaseModel):
    images: list[_Item] = Field(default_factory=list)


def targets(assets: list[Asset], base: Path) -> list[Asset]:
    """점검할 장면: AI가 만든 새 그림(영상 제외)이고 파일이 있는 것."""
    out = []
    for a in assets:
        img = a.image
        if img.source != "generated" or not img.path or is_video_path(img.path):
            continue
        if img.check is not None and img.check.path == img.path:
            continue  # 이미 본 그림 (다시 쓰는 그림은 한도를 쓰지 않는다)
        if (base / img.path).is_file():
            out.append(a)
    return out[:MAX_IMAGES]


async def check_images(llm: LLMAdapter, assets: list[Asset], base: Path) -> list[str]:
    """그림마다 ImageAsset.check를 채우고, 문제가 있는 장면의 안내 문구를 돌려준다."""
    todo = targets(assets, base)
    if not todo or not llm.supports_images:
        return []
    user = "\n".join(f"{i}: {a.scene_id}" for i, a in enumerate(todo))
    try:
        out = await llm.generate_json(
            "s5_image_check",
            load_prompt("s5_image_check").text,
            user,
            _Result,
            images=[str(base / a.image.path) for a in todo],
        )
    except Exception as e:  # noqa: BLE001 - 보조 기능
        log.warning("그림 점검 실패: %s", type(e).__name__)
        return []
    found = {item.index: item for item in out.images if 0 <= item.index < len(todo)}
    notes = []
    for i, a in enumerate(todo):
        item = found.get(i)
        issues = [k for k in ISSUE_LABEL if item is not None and getattr(item, k)]
        a.image.check = ImageCheck(path=a.image.path, issues=issues)
        if issues:
            labels = ", ".join(ISSUE_LABEL[k] for k in issues)
            notes.append(f"{a.scene_id} 그림: {labels} — '다른 그림'으로 바꿀 수 있어요")
    return notes
