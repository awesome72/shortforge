"""가게 입력 확인: 맞춤법 제안(AI)과 막연한 혜택 되묻기(코드).

사장님이 '떡복기', '확끈하게'라고 적자 대사 3개, 제목 2개, 해시태그, 음성에 그대로 들어갔다
(prj_d27acbc58d8a, 2026-11-02). 혜택이 '주말 특가'뿐이라 대사도 얼마인지 말하지 못했다.
AI는 제안만 하고, 사장님이 누를 때만 바꾼다. 제안은 코드가 다시 걸러 뜻·숫자를 바꾸지 못하게 한다.
"""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata

from pydantic import BaseModel, Field

from app.adapters.base import LLMAdapter
from app.llm import load_prompt

log = logging.getLogger(__name__)

# 맞춤법을 볼 칸. 가게 이름·동네는 고유명사라 보지 않는다
CHECK_FIELDS = {
    "product": "상품",
    "offer": "혜택",
    "period": "기간",
    "pride": "우리 가게 자랑",
    "action": "손님이 할 일",
}
MIN_SIMILARITY = 0.6  # 이보다 많이 바뀌면 맞춤법이 아니라 다시 쓴 것으로 본다
# 얼마나 이득인지 드러나는 말. 없으면 "얼마나 할인되나요?"라고 묻는다
_CONCRETE = re.compile(
    r"\d|반값|무료|공짜|증정|덤|하나\s*더|서비스|[일이삼사오육칠팔구십백천만]\s*(원|%|퍼센트)"
)


class ShopDraft(BaseModel):
    """입력 중인 가게 정보 (검증 전이라 모든 칸이 비어 있을 수 있다)."""

    shop_name: str = Field(default="", max_length=40)
    area: str = Field(default="", max_length=40)
    purpose: str = ""
    product: str = Field(default="", max_length=80)
    offer: str = Field(default="", max_length=80)
    period: str = Field(default="", max_length=40)
    action: str = Field(default="", max_length=40)
    pride: str = Field(default="", max_length=80)


class Fix(BaseModel):
    field: str
    original: str
    fixed: str


class ShopCheck(BaseModel):
    items: list[Fix] = Field(default_factory=list)


def offer_question(draft: ShopDraft) -> str | None:
    """혜택이 막연하면 되묻는다 (AI 없음)."""
    offer = draft.offer.strip()
    if not offer or _CONCRETE.search(offer):
        return None
    return "얼마나 이득인지 적으면 대사가 분명해져요. 예: 1,000원 할인, 20% 할인, 음료 무료"


def _digits(text: str) -> list[str]:
    return re.findall(r"\d+", text)


def accept(fix: Fix, draft: ShopDraft) -> bool:
    """AI 제안 중 맞춤법 수정으로 볼 수 있는 것만 남긴다."""
    if fix.field not in CHECK_FIELDS:
        return False
    current = getattr(draft, fix.field).strip()
    fixed = fix.fixed.strip()
    if not current or fix.original.strip() != current or not fixed or fixed == current:
        return False
    if _digits(fixed) != _digits(current):  # 숫자는 바꾸지 않는다
        return False
    if abs(len(fixed) - len(current)) > max(2, len(current) // 5):
        return False
    # 자모로 풀어 비교한다: 글자 단위면 '떡복기'→'떡볶이'도 3자 중 1자만 같아 버려졌다
    a, b = unicodedata.normalize("NFD", current), unicodedata.normalize("NFD", fixed)
    return difflib.SequenceMatcher(None, a, b).ratio() >= MIN_SIMILARITY


async def spelling(llm: LLMAdapter, draft: ShopDraft) -> list[Fix]:
    """맞춤법 제안. 실패하면 빈 목록 (영상 만들기를 막지 않는다)."""
    values = {f: getattr(draft, f).strip() for f in CHECK_FIELDS}
    lines = [f"- {f}: {v}" for f, v in values.items() if v]
    if not lines:
        return []
    try:
        out = await llm.generate_json(
            "shop_check", load_prompt("shop_check").text, "\n".join(lines), ShopCheck
        )
    except Exception as e:  # noqa: BLE001 - 보조 기능
        log.warning("가게 입력 확인 실패: %s", type(e).__name__)
        return []
    seen: set[str] = set()
    fixes = []
    for fix in out.items:
        if fix.field not in seen and accept(fix, draft):
            seen.add(fix.field)
            clean = {"original": fix.original.strip(), "fixed": fix.fixed.strip()}
            fixes.append(fix.model_copy(update=clean))
    return fixes
