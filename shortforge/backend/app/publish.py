"""업로드 전 체크리스트와 설명란 문구 (M2 · AI 고지, PRD §11 "플랫폼의 AI 생성물 라벨 정책").

프로젝트에서 실제로 쓴 것(합성 음성·AI 이미지·무료 사진·본인 사진)을 보고 만든다.
정책을 단정하지 않고 사용자가 업로드 화면에서 확인할 일을 알려 준다.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.media import is_video_path
from app.schemas.project import Project

MAX_HASHTAGS = 5
COVER_VERSION = 1  # 커버를 만드는 방식(글자 크기·위치·보정)을 바꾸면 올린다


def hashtag(keyword: str) -> str:
    return "#" + re.sub(r"[^\w]", "", keyword.replace(" ", ""))


def _is_video(a) -> bool:
    return is_video_path(a.image.path)


def _count(assets: list) -> str:
    """ "사진 3장", "동영상 2개", "사진 2장·동영상 1개"."""
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
    stock = [a for a in assets if a.image.source == "stock" and a.image.path]
    user = [a for a in assets if a.image.source == "user" and a.image.path]
    voices = sorted({a.voice.voice for a in assets})
    models = sorted({(a.image.provider or "").split(":")[-1] for a in generated} - {""})

    checklist = [
        {
            "id": "synthetic",
            "text": "AI 목소리"
            + (f"·AI 생성 이미지 {len(generated)}장" if generated else "")
            + "을 썼다. 실제 사람·장면처럼 보일 수 있으면 YouTube 업로드 화면의 "
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
    if user:
        checklist.append(
            {
                "id": "portrait",
                "text": f"본인 {_count(user)}에 다른 사람이 나오면 공개 동의를 받았다 (초상권)",
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
    checklist.append(
        {
            "id": "commercial",
            "text": "수익을 낼 거라면 무료 도구의 상업 이용 조건을 확인했다 "
            "(AI 목소리, AI 그림, 무료 사진 사이트의 약관)",
            "auto": False,
        }
    )

    lines: list[str] = []
    if p.strategy:
        lines += [p.strategy.titles[0], ""]
    used = ["AI 합성 음성(Microsoft Edge TTS)"]
    if generated:
        used.append(f"AI 생성 이미지({', '.join(models) or 'AI'})")
    if music and music.source == "generated":
        used.append("배경음악(ShortForge가 직접 합성한 곡)")
    # 마지막 항목이 "이미지(…)"면 를, "음성(…)"·"곡)"이면 을
    particle = "를" if used[-1].startswith("AI 생성 이미지") else "을"
    lines.append(f"이 영상은 {', '.join(used)}{particle} 사용해 만들었습니다.")
    if stock:
        lines += ["", "사진·영상 출처:" if any(_is_video(a) for a in stock) else "사진 출처:"]
        lines += [f"- {a.image.credit}" for a in stock if a.image.credit]
    tags = [hashtag(k) for k in (p.input.keywords if p.input else [])][:MAX_HASHTAGS]
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
