"""단계 실행 전 '내용' 조건과 사용자가 할 일 안내.

오케스트레이터의 blockers는 앞 단계가 done인지만 본다. 그런데 5단계가 끝났어도
장면 이미지가 비어 있으면 6단계는 반드시 실패한다(실제로 사용자가 6단계를 6번 눌렀다).
여기서 그런 조건을 미리 판정해, 실행 버튼을 잠그고 무엇을 하면 되는지 지금 설정에 맞게 알려 준다.
"""

from __future__ import annotations

from app.config import Settings
from app.schemas.project import Project, StepId


def has_cloudflare(s: Settings) -> bool:
    return bool(s.cloudflare_account_id and s.cloudflare_api_token)


def unused_image_sources(s: Settings) -> list[str]:
    """키는 있는데 이미지 방식에 들어 있지 않은 소스 (설정 불일치 안내용)."""
    sources = set(s.image_sources)
    out = []
    if has_cloudflare(s) and "cloudflare" not in sources:
        out.append("Cloudflare AI 생성")
    if s.pixabay_api_key and not sources & {"stock", "pixabay"}:
        out.append("Pixabay 무료 사진")
    return out


def image_hint(s: Settings) -> str:
    """이미지가 빈 장면을 채우는 방법. 지금 이미지 방식과 가진 키에 맞춰 고른다."""
    if not s.image_sources:  # IMAGE_MODE=upload
        if has_cloudflare(s):
            how = (
                "Cloudflare 키가 있으니 설정 → 이미지에서 'AI 생성'으로 바꾸고 "
                "5단계를 다시 실행한다"
            )
        elif s.pixabay_api_key:
            how = (
                "Pixabay 키가 있으니 설정 → 이미지에서 '무료 사진'으로 바꾸고 5단계를 다시 실행한다"
            )
        else:
            how = (
                "설정 → 이미지에서 무료 사진(Pixabay)·AI 생성(Cloudflare) 키를 넣고 방식을 바꾼 뒤 "
                "5단계를 다시 실행한다"
            )
        return (
            "이미지 방식이 '본인 사진만'이라 이미지를 만들지 않았다. "
            f"{how}. 또는 5단계 장면 카드의 '사진 교체'로 사진을 올린다"
        )
    return (
        f"이미지 소스({s.image_mode})가 이 장면의 이미지를 주지 못했다(한도 초과·오류). "
        "5단계 장면 카드의 '다른 이미지'를 누르거나 '사진 교체'로 사진을 올린다. "
        "설정을 바꿨다면 5단계를 다시 실행한다"
    )


def missing_media(project: Project) -> tuple[list[str], list[str]]:
    """(이미지가 없는 장면, 음성이 없는 장면). 5단계 출력이 없으면 둘 다 빈 목록."""
    no_image, no_voice = [], []
    for a in project.assets or []:
        if not a.image.path:
            no_image.append(a.scene_id)
        if not a.voice.path:
            no_voice.append(a.scene_id)
    return no_image, no_voice


def not_ready(project: Project, step: StepId, s: Settings) -> str | None:
    """앞 단계는 끝났지만 내용이 모자라 이 단계가 실패할 이유. 없으면 None."""
    if step != "s6" or project.assets is None:
        return None
    no_image, no_voice = missing_media(project)
    if no_image:
        return f"이미지가 없는 장면이 있다: {', '.join(no_image)} — {image_hint(s)}"
    if no_voice:
        return f"음성이 없는 장면이 있다: {', '.join(no_voice)} — 5단계를 다시 실행한다"
    return None
