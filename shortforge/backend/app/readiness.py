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
    """이미지가 빈 장면을 채우는 방법. 지금 방식과 가진 키에 맞춰 고른다(화면에 그대로 보인다)."""
    if not s.image_sources and s.image_mode == "auto":  # 키가 아직 없다
        return (
            "그림을 만들 키가 아직 없어요. 설정에서 Cloudflare(AI 그림)나 Pixabay(무료 사진) 키를 "
            "넣으면 방식을 바꾸지 않아도 바로 쓰고, 5단계를 다시 하면 빈 장면이 채워져요. "
            "또는 장면마다 '사진 교체'로 사진을 올려 주세요"
        )
    if not s.image_sources:  # IMAGE_MODE=upload
        if has_cloudflare(s):
            how = (
                "Cloudflare 키가 있으니 설정 → 이미지에서 'AI 생성'으로 바꾸고 "
                "5단계를 다시 해 주세요"
            )
        elif s.pixabay_api_key:
            how = (
                "Pixabay 키가 있으니 설정 → 이미지에서 '무료 사진'으로 바꾸고 "
                "5단계를 다시 해 주세요"
            )
        else:
            how = (
                "설정 → 이미지에서 무료 사진(Pixabay)·AI 생성(Cloudflare) 키를 넣고 방식을 바꾼 뒤 "
                "5단계를 다시 해 주세요"
            )
        return (
            "이미지 방식이 '본인 사진만'이라 그림을 만들지 않았어요. "
            f"{how}. 또는 5단계 장면 카드의 '사진 교체'로 사진을 올려 주세요"
        )
    only_demo = s.image_sources == ["hfspace"]  # 키 없이 무료 데모 서버만 쓰는 중
    keys = (
        ""
        if not only_demo
        else (
            " 무료 데모 서버만 쓰고 있어 붐비면 실패할 수 있어요. 설정에서 Cloudflare(AI 그림)나 "
            "Pixabay(무료 사진) 키를 넣으면 더 안정적이에요."
        )
    )
    return (
        "그림을 만드는 곳이 이 장면의 그림을 주지 못했어요(한도 초과·오류). "
        "5단계 장면 카드의 '다른 이미지'를 누르거나 '사진 교체'로 사진을 올려 주세요. "
        "설정을 바꿨다면 5단계를 다시 해 주세요." + keys
    )


def no_generator_hint(s: Settings) -> str:
    """'다른 그림'을 눌렀는데 그림을 만드는 곳이 하나도 없을 때.

    방식은 골랐는데 그 키가 없으면(예: 무료 사진인데 Pixabay 키 없음) 조립 단계에서 소스가 빠져
    '본인 사진만'처럼 동작한다. 그때 '본인 사진만이라'고 하면 고른 방식과 달라 헷갈렸다.
    """
    if s.image_mode == "upload" or not s.image_sources:
        return image_hint(s)
    return (
        "고른 이미지 방식에 필요한 키가 없어 그림을 만들 수 없어요. 설정에서 키를 넣거나 "
        "이미지 방식을 '자동'으로 바꿔 주세요. 또는 '사진 교체'로 사진을 올려 주세요"
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
        return f"그림이 없는 장면이 있어요: {', '.join(no_image)} — {image_hint(s)}"
    if no_voice:
        return f"목소리가 없는 장면이 있어요: {', '.join(no_voice)} — 5단계를 다시 해 주세요"
    return None
