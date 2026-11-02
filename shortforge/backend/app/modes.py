"""프로젝트 모드: 취미(hobby)와 소상공인(business).

렌더·음성·자막·음악·다듬기는 공유하고, 입력과 기획만 다르다. 모드별 차이는 이 파일에 모은다.
단계는 `if mode`를 흩뿌리지 않고 여기의 값과 함수를 쓴다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.config import Settings
from app.schemas.project import PURPOSE_LABEL, BusinessBrief, Input, Scene


@dataclass(frozen=True)
class ModeProfile:
    name: str
    world_search: bool  # 해외 레퍼런스 (D16). 가게 홍보에는 같은 업종·지역이 맞다
    strategy_overlay: str | None = None  # S4 규칙에 덧붙이는 프롬프트


HOBBY = ModeProfile("hobby", world_search=True)
BUSINESS = ModeProfile("business", world_search=False, strategy_overlay="s4_business")


def profile_for(inp: Input) -> ModeProfile:
    return BUSINESS if inp.mode == "business" else HOBBY


def markets(settings: Settings, inp: Input) -> list[tuple[str, str]]:
    return settings.markets if profile_for(inp).world_search else []


def business_block(inp: Input) -> str:
    """LLM에 넘기는 가게 정보. 취미 모드는 빈 문자열이라 입력이 지금과 같다."""
    b = inp.business
    if inp.mode != "business" or b is None:
        return ""
    fields = {
        "가게 이름": b.shop_name,
        "동네": b.area,
        "목적": PURPOSE_LABEL[b.purpose],
        "상품": b.product,
        "혜택": b.offer,
        "기간": b.period,
        "우리 가게 자랑": b.pride,
        "손님이 할 일": b.action,
    }
    lines = [f"- {k}: {v}" for k, v in fields.items() if v]
    return "\n\n[가게 정보] 여기 있는 사실만 쓴다\n" + "\n".join(lines)


# ── 광고 사실 ───────────────────────────────────────────
# 가격·기간이 입력과 다르면 사장님이 거짓 광고를 하게 된다. 한국어 금액·날짜를 정규식으로 해석해
# 대조하는 방식은 구멍과 오탐이 끝없이 나왔다. 그래서 틀리면 안 되는 대사는 AI가 쓰지 않는다:
# 혜택과 끝맺음은 입력값을 코드로 넣고, 나머지 장면에는 입력에 없는 숫자를 쓰지 못하게 한다.
# 뜻까지 보지는 못하므로 통과가 사실을 보장하지 않는다. 대사는 사장님이 확인한다.

FACT_PREFIX = "가게 정보에 없는 말이 있어요"

# 숫자 + 바로 뒤 글자. 입력이 '11월 말까지'면 '11월'만 되고 '11일'은 안 된다
_NUMBER = re.compile(r"(\d[\d,.]*)\s*([가-힣%])?")
_KOREAN_AMOUNT = re.compile(
    r"[일이삼사오육칠팔구십백천만]*[십백천만]\s*원(?!하|해|한|재|료|장|단)"
    r"|(?<![가-힣])[일이삼사오육칠팔구십]+\s*(?:퍼센트|프로)(?![가-힣])"
)
_BANNED = (
    r"할인", r"무료(?!한)", r"공짜", r"반값", r"절반", r"증정", r"사은품", r"경품", r"쿠폰",
    r"세일", r"특가", r"서비스로", r"덤으로", r"원\s*플러스\s*원", r"리필",
    r"최고(?!기온)", r"최저가", r"유일", r"무조건", r"보장", r"완치", r"특효", r"다이어트",
    r"면역", r"맛집", r"전통(?!시장)", r"국내산", r"유기농", r"난리", r"입소문", r"소문난",
    r"인기", r"대박", r"일등", r"줄\s*(?:을\s*)?서", r"많은 분", r"분들이 많", r"손님이 많",
    r"사람들이\s*(?:\S+\s*){0,3}모이", r"몰리", r"오늘만(?!큼)", r"오늘뿐", r"하루만(?!에)",
    r"직접\s*(?:반죽|담그|담가|만드|만들|다듬|빚)",
    r"(?:오늘|내일|모레|주말|이번\s*주|다음\s*주|이번\s*달|월말|연말)\S*까지",
    r"[일이삼사오육칠팔구십]+[월일]까지",
)  # fmt: skip


def _token(number: str) -> str:
    return number.replace(",", "").rstrip(".")


def _source(brief: BusinessBrief) -> str:
    fields = (
        brief.shop_name, brief.area, brief.product, brief.offer, brief.period, brief.action,
        brief.pride,
    )  # fmt: skip
    return unicodedata.normalize("NFKC", " ".join(fields))


def fact_problems(texts: list[str], brief: BusinessBrief) -> list[str]:
    """입력에 없는 숫자·금액·혜택·과장 표현. 비어 있으면 통과."""
    source = _source(brief)
    plain = source.replace(" ", "")
    known = {_token(n) + unit for n, unit in _NUMBER.findall(source)}
    known |= {_token(n) for n, _ in _NUMBER.findall(source)}
    problems: list[str] = []

    def add(word: str) -> None:
        message = f"{FACT_PREFIX}: '{word.strip()}'"
        if message not in problems:
            problems.append(message)

    for raw in texts:
        text = unicodedata.normalize("NFKC", raw)
        for number, unit in _NUMBER.findall(text):
            if _token(number) + unit not in known:
                add(number.rstrip(",.") + unit)
        for found in _KOREAN_AMOUNT.findall(text):
            if found.replace(" ", "") not in plain:
                add(found)
        for pattern in _BANNED:
            for found in re.findall(pattern, text):
                if found.replace(" ", "") not in plain:
                    add(found)
    return problems


def _spoken(text: str) -> str:
    """대사 정리(tts_script)는 괄호 안을 지운다. 조건이 사라지면 안 되므로 미리 풀어 쓴다."""
    text = re.sub(r"[()\[\]{}]", ", ", text).replace("~", " 부터 ")
    return " ".join(text.split()).strip(" ,.!")


def offer_line(brief: BusinessBrief) -> str:
    """혜택 장면 대사. 혜택이 없으면 기간이나 공지 내용만, 말할 것이 없으면 빈 문자열."""
    head = _spoken(brief.offer) or (_spoken(brief.product) if brief.purpose == "notice" else "")
    period = _spoken(brief.period)
    if head and period:
        return f"{head}! {period}."
    return f"{head or period}." if head or period else ""


def fix_shop_lines(scenes: list[Scene], brief: BusinessBrief) -> list[Scene]:
    """틀리면 안 되는 두 장면은 입력값을 그대로 넣는다: 혜택 장면과 손님이 할 일."""
    out = list(scenes)
    if brief.action.strip():
        out[-1] = out[-1].model_copy(update={"role": "cta", "line": _spoken(brief.action) + "."})
    line = offer_line(brief)
    if line:
        free = [i for i, s in enumerate(out[:-1]) if i and s.role != "payoff"] or [len(out) - 2]
        spot = next((i for i, s in enumerate(out[:-1]) if s.role == "offer"), free[-1])
        out[spot] = out[spot].model_copy(update={"role": "offer", "line": line})
    return out


def scene_media(inp: Input, scene_count: int) -> list[str]:
    """장면에 넣을 내 사진. 소상공인 모드는 AI 그림을 쓰지 않아 사진을 돌려 모든 장면을 채운다.

    AI에게 음식·매장을 그리지 말라고 해도 '햇살 창가'에 음식과 가짜 간판을 그렸다 (2026-11-02).
    실제와 다른 그림은 손님을 속일 수 있어 규칙이 아니라 구조로 막는다.
    """
    media = inp.user_media
    if inp.mode != "business" or not media:
        return media
    return [media[i % len(media)] for i in range(scene_count)]
