"""업로드 전 체크리스트와 설명란 문구 (M2 · AI 고지, PRD §11 "플랫폼의 AI 생성물 라벨 정책").

프로젝트에서 실제로 쓴 것(합성 음성·AI 이미지·무료 사진·본인 사진)을 보고 만든다.
정책을 단정하지 않고 사용자가 업로드 화면에서 확인할 일을 알려 준다.
"""

from __future__ import annotations

import re

from app.schemas.project import Project

MAX_HASHTAGS = 5


def hashtag(keyword: str) -> str:
    return "#" + re.sub(r"[^\w]", "", keyword.replace(" ", ""))


def publish_kit(p: Project) -> dict:
    assets = p.assets or []
    generated = [a for a in assets if a.image.source == "generated" and a.image.path]
    stock = [a for a in assets if a.image.source == "stock" and a.image.path]
    user = [a for a in assets if a.image.source == "user" and a.image.path]
    voices = sorted({a.voice.voice for a in assets})
    models = sorted({(a.image.provider or "").split(":")[-1] for a in generated} - {""})

    checklist = [
        {
            "id": "synthetic",
            "text": "합성 음성"
            + (f"·AI 생성 이미지 {len(generated)}장" if generated else "")
            + "을 썼다. 실제 사람·장면처럼 보일 수 있으면 YouTube 업로드 화면의 "
            "'변경되거나 합성된 콘텐츠' 항목을 '예'로 고른다 (최신 정책은 업로드 화면에서 확인)",
            "auto": False,
        },
        {
            "id": "references",
            "text": "레퍼런스 영상의 영상·이미지·음성은 쓰지 않았다 "
            "(구조만 참고, 제목 유사도 검사 통과)",
            "auto": True,
        },
    ]
    if stock:
        checklist.append(
            {
                "id": "credits",
                "text": f"무료 사진 {len(stock)}장의 출처를 설명란에 넣었다 (아래 문구에 포함)",
                "auto": False,
            }
        )
    if user:
        checklist.append(
            {
                "id": "portrait",
                "text": f"본인 사진 {len(user)}장에 다른 사람이 나오면 공개 동의를 받았다 (초상권)",
                "auto": False,
            }
        )
    checklist.append(
        {
            "id": "commercial",
            "text": "수익 목적이면 무료 도구의 상업 이용 조건을 확인했다 "
            "(Edge-TTS 음성, AI 이미지 모델, 무료 사진 사이트의 약관)",
            "auto": False,
        }
    )

    lines: list[str] = []
    if p.strategy:
        lines += [p.strategy.titles[0], ""]
    used = ["AI 합성 음성(Microsoft Edge TTS)"]
    if generated:
        used.append(f"AI 생성 이미지({', '.join(models) or 'AI'})")
    particle = "를" if generated else "을"  # 마지막 항목이 "이미지(…)"면 를, "음성(…)"이면 을
    lines.append(f"이 영상은 {', '.join(used)}{particle} 사용해 만들었습니다.")
    if stock:
        lines += ["", "사진 출처:"]
        lines += [f"- {a.image.credit}" for a in stock if a.image.credit]
    tags = [hashtag(k) for k in (p.input.keywords if p.input else [])][:MAX_HASHTAGS]
    if tags:
        lines += ["", " ".join(dict.fromkeys(tags)) + " #shorts"]

    return {
        "checklist": checklist,
        "description": "\n".join(lines),
        "voices": voices,
        "counts": {"generated": len(generated), "stock": len(stock), "user": len(user)},
    }
