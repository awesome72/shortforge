"""업로드 전 체크리스트와 설명란 문구 (M2 · AI 고지, PRD §11 "플랫폼의 AI 생성물 라벨 정책").

프로젝트에서 실제로 쓴 것(합성 음성·AI 이미지·무료 사진·본인 사진)을 보고 만든다.
정책을 단정하지 않고 사용자가 업로드 화면에서 확인할 일을 알려 준다.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.media import is_video_path
from app.modes import (
    ad_brief,
    fact_problems,
    listing_checklist,
    listing_description,
    shop_checklist,
    shop_description,
    taste_problems,
)
from app.schemas.project import BusinessBrief, ListingBrief, Project

MAX_HASHTAGS = 5
COVER_VERSION = 1  # 커버를 만드는 방식(글자 크기·위치·보정)을 바꾸면 올린다


def hashtag(keyword: str) -> str:
    return "#" + re.sub(r"[^\w]", "", keyword.replace(" ", ""))


def _is_video(a) -> bool:
    return is_video_path(a.image.path)


def _origin(a) -> str:
    """이 장면의 원본 출처. 그림을 움직인 영상이면 원래 그림의 출처다."""
    return a.image.still.source if a.image.still and _is_video(a) else a.image.source


def _ai_label(generated: list, clips: list) -> str:
    """ "AI 생성 이미지 3장", "AI 생성 이미지 2장·영상 1개", "AI 생성 영상 1개"."""
    images = len(generated) - len(clips)
    parts = ([f"이미지 {images}장"] if images else []) + ([f"영상 {len(clips)}개"] if clips else [])
    return "AI 생성 " + "·".join(parts)


def _count(assets: list) -> str:
    """ "사진 3장", "동영상 2개", "사진 2장·동영상 1개".

    같은 사진을 여러 장면에 써도 한 장으로 센다 (사진 5장이 '6장'으로 나왔다).
    """
    assets = list({a.image.path: a for a in assets}.values())
    videos = sum(1 for a in assets if _is_video(a))
    photos = len(assets) - videos
    parts = ([f"사진 {photos}장"] if photos else []) + ([f"동영상 {videos}개"] if videos else [])
    return "·".join(parts)


COVER_TITLE_FILE = "render/cover_title.txt"  # 사용자가 고친 커버 문구 (Project JSON 밖)
MAX_COVER_TITLE = 60


def cover_title(p: Project, project_dir: Path) -> str:
    """커버 문구: 사용자가 고친 문구가 있으면 그것, 없으면 4단계 첫 제목."""
    try:
        custom = (project_dir / COVER_TITLE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        custom = ""
    return custom or (p.strategy.titles[0] if p.strategy else "")


def save_cover_title(project_dir: Path, title: str) -> str:
    """문구를 정리해 저장한다. 빈 문구면 4단계 제목으로 돌아간다(파일을 지운다)."""
    clean = " ".join(title.replace("\n", " / ").split())[:MAX_COVER_TITLE]
    path = project_dir / COVER_TITLE_FILE
    if clean:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(clean, encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    return clean


def cover_path(p: Project, project_dir: Path) -> Path | None:
    """커버 파일 위치. 문구·첫 장면 이미지가 바뀌면 이름이 바뀌어 새로 만든다."""
    if not p.strategy or not p.timeline:
        return None
    image = project_dir / p.timeline.scenes[0].image
    try:
        stamp = image.stat().st_mtime_ns
    except OSError:
        stamp = 0
    title = cover_title(p, project_dir)
    key = f"{COVER_VERSION}|{title}|{p.timeline.scenes[0].image}|{stamp}"
    return project_dir / "render" / f"cover_{hashlib.sha1(key.encode()).hexdigest()[:12]}.jpg"


def publish_kit(p: Project, cover: Path | None = None, cover_text: str = "") -> dict:
    """cover: 이미 만든 커버 파일 (있을 때만), cover_text: 지금 커버 문구."""
    assets = p.assets or []
    generated = [a for a in assets if a.image.source == "generated" and a.image.path]
    # 그림을 움직인 영상(D19)은 AI 생성물이면서 원본의 출처·초상권 확인도 그대로 필요하다
    stock = [a for a in assets if _origin(a) == "stock" and a.image.path]
    user = [a for a in assets if _origin(a) == "user" and a.image.path]
    clips = [a for a in generated if _is_video(a)]
    voices = sorted({a.voice.voice for a in assets})
    models = sorted({(a.image.provider or "").split(":")[-1] for a in generated} - {""})
    brief = ad_brief(p.input) if p.input else None
    shop = brief if isinstance(brief, BusinessBrief) else None
    listing = brief if isinstance(brief, ListingBrief) else None

    checklist = [
        *(shop_checklist(shop) if shop else []),
        *(listing_checklist(listing) if listing else []),
        {
            "id": "synthetic",
            "text": "AI 목소리"
            + (f"·{_ai_label(generated, clips)}" if generated else "")
            + ("을" if generated and not clips else "를")
            + " 썼다. 실제 사람·장면처럼 보일 수 있으면 YouTube 업로드 화면의 "
            "'변경되거나 합성된 콘텐츠' 항목을 '예'로 고른다 (최신 정책은 업로드 화면에서 확인)",
            "auto": False,
        },
        {
            "id": "references",
            "text": "참고한 인기 영상의 화면·그림·소리는 쓰지 않았다 "
            "(구성만 참고했고, 제목이 겹치지 않는지 확인했다)",
            "auto": True,
        },
    ]
    if stock:
        checklist.append(
            {
                "id": "credits",
                "text": f"무료 {_count(stock)}의 출처를 설명란에 넣었다 (아래 문구에 포함)",
                "auto": False,
            }
        )
    if user and not listing:
        checklist.append(
            {
                "id": "portrait",
                "text": "사진에 손님·직원 얼굴이 나오면 공개 동의를 받았다 (초상권)"
                if shop
                else f"본인 {_count(user)}에 다른 사람이 나오면 공개 동의를 받았다 (초상권)",
                "auto": False,
            }
        )
    music = p.timeline.audio if p.timeline and p.timeline.audio.bgm else None
    if music and music.source == "user":
        checklist.append(
            {
                "id": "music",
                "text": "직접 올린 배경음악을 이 영상에 쓸 권리가 있다 "
                "(유명 곡은 YouTube 저작권 확인(Content ID)으로 수익이 막히거나 "
                "소리가 꺼질 수 있다)",
                "auto": False,
            }
        )
    if clips and shop:
        # AI가 사진을 움직이면서 음식 모양·간판 글자·가격표가 바뀔 수 있다 (사장님 이름의 광고다)
        checklist.append(
            {
                "id": "shop_motion",
                "text": f"AI로 움직인 장면 {len(clips)}개를 끝까지 봤다. 음식 모양·양, 간판·메뉴판 "
                "글자, 가격이 원래 사진과 같다",
                "auto": False,
            }
        )
    if clips and listing:
        # 국토부 고시 2023-542 제6조①: 해당 매물의 사진이 아닌 것(움직이며 달라진 방)은
        # 거짓 광고가 될 수 있다
        checklist.append(
            {
                "id": "listing_motion",
                "text": f"AI로 움직인 장면 {len(clips)}개를 끝까지 봤다. 방 크기·구조·창·가구가 "
                "원래 사진과 같고, 없는 공간이나 물건이 생기지 않았다",
                "auto": False,
            }
        )
    if clips:
        # LTX-Video 라이선스: 기계가 만들었음을 밝혀야 하고, 동의 없는 사칭은 금지다
        checklist.append(
            {
                "id": "ai_video",
                "text": f"AI로 만든 영상 {len(clips)}개가 있다. 설명란에 AI로 만들었다고 밝혔고 "
                "(아래 문구에 포함), 다른 사람을 동의 없이 흉내 내지 않았다 (AI 모델 사용 조건)",
                "auto": False,
            }
        )
    checklist.append(
        {
            "id": "commercial",
            "text": f"{'매물' if listing else '가게'} 홍보는 상업적 이용이다. "
            "Microsoft Edge 음성과 Google Gemini 무료 등급을 상업용으로 써도 되는지 "
            "각 서비스 약관에서 확인했다"
            if brief
            else "수익을 낼 거라면 무료 도구의 상업 이용 조건을 확인했다 "
            "(AI 목소리, AI 그림·영상, 무료 사진 사이트의 약관)",
            "auto": False,
        }
    )

    lines: list[str] = []
    if p.strategy:
        lines += [p.strategy.titles[0], ""]
    if shop:
        lines += [*shop_description(shop), ""]
    if listing:  # 영상 끝 카드와 같은 명시 항목을 글로도 남긴다
        lines += ["[매물 정보]", *listing_description(listing), ""]
    used = ["AI 합성 음성(Microsoft Edge TTS)"]
    if generated:
        kind = "영상" if len(clips) == len(generated) else "이미지·영상" if clips else "이미지"
        used.append(f"AI 생성 {kind}({', '.join(models) or 'AI'})")
    if music and music.source == "generated":
        used.append("배경음악(ShortForge가 직접 합성한 곡)")
    # 마지막 항목이 "이미지(…)"면 를, "음성(…)"·"곡)"이면 을
    particle = "를" if used[-1].startswith("AI 생성 이미지(") else "을"
    lines.append(f"이 영상은 {', '.join(used)}{particle} 사용해 만들었습니다.")
    if stock:
        lines += ["", "사진·영상 출처:" if any(_is_video(a) for a in stock) else "사진 출처:"]
        lines += [f"- {a.image.credit}" for a in stock if a.image.credit]
    keywords = list(p.input.keywords) if p.input else []
    if shop:
        # 키워드는 검색용이라 '맛집' 같은 말이 있을 수 있다. 사장님 글에는 넣지 않는다.
        # 공백을 뺀 태그는 '많은 분' 같은 표현을 놓쳐 태그로 바꾸기 전에 본다
        keywords = [
            k for k in keywords if not (fact_problems([k], shop) or taste_problems([k], shop))
        ]
        keywords = [shop.shop_name, shop.area, *keywords]
    if listing:
        keywords = [
            k for k in keywords if not (fact_problems([k], listing) or taste_problems([k], listing))
        ]
    tags = [t for t in dict.fromkeys(hashtag(k) for k in keywords) if t != "#"][:MAX_HASHTAGS]
    if tags:
        lines += ["", " ".join(dict.fromkeys(tags)) + " #shorts"]

    return {
        "checklist": checklist,
        "description": "\n".join(lines),
        "voices": voices,
        "counts": {"generated": len(generated), "stock": len(stock), "user": len(user)},
        "cover": f"render/{cover.name}" if cover else None,
        "cover_title": cover_text or (p.strategy.titles[0] if p.strategy else ""),
    }
