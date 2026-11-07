"""프로젝트 모드: 취미(hobby), 소상공인(business), 매물 홍보(listing).

렌더·음성·자막·음악·다듬기는 공유하고, 입력과 기획만 다르다. 모드별 차이는 이 파일에 모은다.
단계는 `if mode`를 흩뿌리지 않고 여기의 값과 함수를 쓴다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.adapters.base import EndCard
from app.config import Settings
from app.schemas.project import (
    DEAL_LABEL,
    LISTING_CARD_SEC,
    PHOTO_KIND_LABEL,
    PROPERTY_LABEL,
    PURPOSE_LABEL,
    BusinessBrief,
    Input,
    ListingBrief,
    Scene,
)

# 사실 검사·대사 고정을 받는 광고 입력 (가게 정보 또는 매물 정보)
Brief = BusinessBrief | ListingBrief


@dataclass(frozen=True)
class ModeProfile:
    name: str
    world_search: bool  # 해외 레퍼런스 (D16). 가게 홍보에는 같은 업종·지역이 맞다
    strategy_overlay: str | None = None  # S4 규칙에 덧붙이는 프롬프트


HOBBY = ModeProfile("hobby", world_search=True)
BUSINESS = ModeProfile("business", world_search=False, strategy_overlay="s4_business")
LISTING = ModeProfile("listing", world_search=False, strategy_overlay="s4_listing")


def profile_for(inp: Input) -> ModeProfile:
    return {"business": BUSINESS, "listing": LISTING}.get(inp.mode, HOBBY)


def is_ad(inp: Input | None) -> bool:
    """실제 사진만 쓰고 틀리면 안 되는 대사를 코드가 넣는 홍보 모드 (가게·매물)."""
    return inp is not None and inp.mode in ("business", "listing")


def end_hold(inp: Input) -> int:
    """말이 끝난 뒤 끝 화면만 보여 줄 시간(초). 매물은 정보 카드를 읽을 시간이다."""
    return LISTING_CARD_SEC if inp.mode == "listing" else 0


def ad_brief(inp: Input) -> Brief | None:
    """사실 검사의 근거가 되는 입력. 취미 모드는 None."""
    if inp.mode == "business":
        return inp.business
    if inp.mode == "listing":
        return inp.listing
    return None


def markets(settings: Settings, inp: Input) -> list[tuple[str, str]]:
    return settings.markets if profile_for(inp).world_search else []


def business_block(inp: Input) -> str:
    """LLM에 넘기는 가게 정보. 취미 모드는 빈 문자열이라 입력이 지금과 같다."""
    if inp.mode == "listing" and inp.listing is not None:
        return listing_block(inp.listing) + photo_block(inp)
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
    return "\n\n[가게 정보] 여기 있는 사실만 쓴다\n" + "\n".join(lines) + photo_block(inp)


def photo_block(inp: Input) -> str:
    """가진 사진 목록. 4단계 장면 묘사가 없는 사진(사장님 인사·간판)을 전제했다 (2026-11-02:
    떡볶이 사진 1장에 '앞치마 두르고 인사', '간판 앞에서 손짓' 장면)."""
    if not inp.user_media:
        return ""
    counts: dict[str, int] = {}
    for m in inp.user_media:
        kind = inp.media_kinds.get(m)
        counts[kind or ""] = counts.get(kind or "", 0) + 1
    known = [f"{PHOTO_KIND_LABEL[k]} {n}장" for k, n in counts.items() if k]
    unknown = counts.get("", 0)
    parts = known + ([f"종류 모름 {unknown}장"] if unknown else [])
    # 매물은 대본이 사진 없는 공간을 말하지 않게 주요 공간을 모두 알린다
    needed = (
        ("living", "room", "kitchen", "bath", "view", "exterior")
        if inp.mode == "listing"
        else ("shop", "owner")
    )
    missing = [PHOTO_KIND_LABEL[k] for k in needed if k not in counts]
    out = f"\n\n[가진 사진] {', '.join(parts)}"
    if missing and not unknown:
        out += f" (없음: {', '.join(missing)})"
    return out


# ── 광고 사실 ───────────────────────────────────────────
# 가격·기간이 입력과 다르면 사장님이 거짓 광고를 하게 된다. 한국어 금액·날짜를 정규식으로 해석해
# 대조하는 방식은 구멍과 오탐이 끝없이 나왔다. 그래서 틀리면 안 되는 대사는 AI가 쓰지 않는다:
# 혜택과 끝맺음은 입력값을 코드로 넣고, 나머지 장면에는 입력에 없는 숫자를 쓰지 못하게 한다.
# 뜻까지 보지는 못하므로 통과가 사실을 보장하지 않는다. 대사는 사장님이 확인한다.

FACT_PREFIX = "가게 정보에 없는 말이 있어요"
LISTING_FACT_PREFIX = "매물 정보에 없는 말이 있어요"


def fact_prefix(brief: Brief) -> str:
    return LISTING_FACT_PREFIX if isinstance(brief, ListingBrief) else FACT_PREFIX


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


# 입력에 없을 수 있지만 틀렸다고 단정할 수 없는 맛·정성 표현. 다시 쓰게 하지 않고 사장님께 보여 준다
_TASTE = (
    r"바삭", r"쫄깃", r"촉촉", r"담백", r"고소", r"얼큰", r"칼칼", r"매콤", r"달콤", r"새콤",
    r"짭짤", r"감칠맛", r"깊은\s*맛", r"진한\s*(?:맛|국물)", r"부드[러럽]\S*", r"신선", r"푸짐",
    r"육즙", r"입안\s*가득", r"정성",
    # 가게 상태 주장 (2026-11-03 무료 경로 실측: 비운 '자랑' 자리에 "언제나 깔끔하게 준비" )
    r"깔끔", r"청결", r"위생", r"엄선", r"최고급", r"정직",
)  # fmt: skip


def _token(number: str) -> str:
    return number.replace(",", "").rstrip(".")


def _source(brief: Brief) -> str:
    if isinstance(brief, ListingBrief):
        fields = [
            v for k, v in brief.model_dump().items() if isinstance(v, str) and k not in _CODES
        ]
        fields += [PROPERTY_LABEL[brief.prop_type], DEAL_LABEL[brief.deal]]
    else:
        fields = [
            brief.shop_name, brief.area, brief.product, brief.offer, brief.period, brief.action,
            brief.pride,
        ]  # fmt: skip
    return unicodedata.normalize("NFKC", " ".join(fields))


# 코드 값과 사무소 연락 정보. 대사의 근거가 아니다
# (사무소 주소·전화의 숫자로 대사의 숫자가 통과했다)
_CODES = {
    "prop_type", "deal", "office_address", "office_phone", "reg_no", "agent_name",
    # 카드·설명란 전용 칸. 대본은 쓰지 않는다(s4_listing.md). 이 값의 숫자로 대사가 통과하지 않게
    "area", "floor", "direction", "rooms", "approved", "parking", "maint_fee",
}  # fmt: skip


def fact_problems(texts: list[str], brief: Brief) -> list[str]:
    """입력에 없는 숫자·금액·혜택·과장 표현(사용자에게 보이는 문구). 비어 있으면 통과."""
    return [f"{fact_prefix(brief)}: '{w}'" for w in fact_words(texts, brief)]


def fact_words(texts: list[str], brief: Brief) -> list[str]:
    """fact_problems의 말 목록. 화면은 문구를 다시 읽지 않고 이 목록을 쓴다(문구를 다듬으면
    정규식으로 다시 뽑던 경고가 소리 없이 사라졌다, 코드 리뷰)."""
    source = _source(brief)
    banned = _LISTING_BANNED if isinstance(brief, ListingBrief) else _BANNED
    plain = source.replace(" ", "")
    known = {_token(n) + unit for n, unit in _NUMBER.findall(source)}
    known |= {_token(n) for n, _ in _NUMBER.findall(source)}
    problems: list[str] = []

    def add(word: str) -> None:
        if word.strip() not in problems:
            problems.append(word.strip())

    for raw in texts:
        text = unicodedata.normalize("NFKC", raw)
        for number, unit in _NUMBER.findall(text):
            if _token(number) + unit not in known:
                add(number.rstrip(",.") + unit)
        for found in _KOREAN_AMOUNT.findall(text):
            if found.replace(" ", "") not in plain:
                add(found)
        for pattern in banned:
            for found in re.findall(pattern, text):
                if found.replace(" ", "") not in plain:
                    add(found)
        if isinstance(brief, ListingBrief):
            for word in listing_claims(text, brief):
                add(word)
    return problems


def taste_problems(texts: list[str], brief: Brief) -> list[str]:
    """입력에 없는 맛·상태 표현. 사실 경고와 같은 모양이라 화면이 대사에 남은 말만 보여 준다."""
    return [f"{fact_prefix(brief)}: '{w}'" for w in taste_words(texts, brief)]


def taste_words(texts: list[str], brief: Brief) -> list[str]:
    plain = _source(brief).replace(" ", "")
    text = unicodedata.normalize("NFKC", " ".join(texts))
    soft = _LISTING_SOFT if isinstance(brief, ListingBrief) else _TASTE
    found = (w for pattern in soft for w in re.findall(pattern, text))
    # '부드럽고'와 '부드러운'은 같은 말이다. 화면에는 대사에 있는 그대로 보여 준다
    known = lambda w: w.replace(" ", "")[: 2 if w.startswith("부드") else None] in plain  # noqa: E731
    return list(dict.fromkeys(w for w in found if not known(w)))


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


def fix_shop_lines(scenes: list[Scene], brief: Brief) -> list[Scene]:
    """틀리면 안 되는 두 장면은 입력값을 그대로 넣는다: 혜택(매물은 가격) 장면과 손님이 할 일."""
    if isinstance(brief, ListingBrief):
        return fix_listing_lines(scenes, brief)
    out = list(scenes)
    if brief.action.strip():
        out[-1] = out[-1].model_copy(update={"role": "cta", "line": _spoken(brief.action) + "."})
    line = offer_line(brief)
    if line:
        free = [i for i, s in enumerate(out[:-1]) if i and s.role != "payoff"] or [len(out) - 2]
        spot = next((i for i, s in enumerate(out[:-1]) if s.role == "offer"), free[-1])
        out[spot] = out[spot].model_copy(update={"role": "offer", "line": line})
    return out


def shop_checklist(brief: BusinessBrief) -> list[dict]:
    """가게 영상 업로드 전 확인. 사장님 이름으로 나가는 말이라 대사는 직접 읽어 보게 한다."""
    facts = " · ".join(v.strip() for v in (brief.offer, brief.period) if v.strip())
    return [
        {
            "id": "shop_facts",
            "title": f"가격·혜택·기간이 실제와 같다: {facts}"  # 비교할 값이 제목에 보여야 한다
            if facts
            else "메뉴 이름과 가게 정보가 실제와 같다",
            "text": f"가격·혜택·기간이 실제와 같다: {facts}"
            if facts
            else "메뉴 이름과 가게 정보가 실제와 같다",
            "auto": False,
        },
        {
            "id": "shop_lines",
            "title": "대사를 읽었고 효능·과장 표현이 없다",
            "text": "대사를 직접 읽어 봤다. 맛·재료·후기 표현이 실제와 같고, "
            "건강·효능을 말하지 않는다 (AI가 쓴 글이다)",
            "auto": False,
        },
        {
            "id": "shop_photos",
            "title": "실제로 파는 메뉴·매장 사진이다",
            "text": "사진이 실제로 파는 메뉴·매장이다 (다른 곳이나 인터넷 사진이 아니다)",
            "auto": False,
        },
    ]


def shop_description(brief: BusinessBrief) -> list[str]:
    """설명란의 가게 안내. 글로 나가므로 음성용으로 풀어 쓴 대사가 아니라 입력 원문을 쓴다."""
    area = brief.area.strip()
    head = f"{brief.shop_name} ({area})" if area else brief.shop_name
    offer = brief.offer.strip() or (brief.product.strip() if brief.purpose == "notice" else "")
    terms = " · ".join(v for v in (offer, brief.period.strip()) if v)
    return [line for line in (head, terms, brief.action.strip()) if line]


def end_card(inp: Input) -> EndCard | None:
    if inp.mode == "listing" and inp.listing is not None:
        return listing_card(inp.listing)
    return shop_card(inp)


def shop_card(inp: Input) -> EndCard | None:
    """가게 영상의 끝 화면: 가게 이름, 동네, 손님이 할 일 (입력 원문 그대로).

    취미 모드는 None이라 렌더가 설정의 채널 이름을 쓴다. 끝 화면은 대사가 끝난 뒤에도
    남아, 손님이 가게 이름과 찾아갈 곳을 한 번 더 본다.
    """
    brief = inp.business
    if inp.mode != "business" or brief is None or not brief.shop_name.strip():
        return None  # 이름이 비면 설정의 채널 이름을 쓴다
    lines = tuple(v for v in (brief.area.strip(), brief.action.strip()) if v)
    return EndCard(title=brief.shop_name.strip(), lines=lines)


def shop_keywords(keywords: list[str], brief: BusinessBrief) -> list[str]:
    """가게 이름이 든 검색어를 빼고, 모자라면 메뉴 중심 검색어로 채운다.

    작은 가게 이름은 YouTube에 숏폼이 거의 없다: 가게 영상 2편 모두 '산본 소담분식'이 들어가
    검색 결과가 비었다(2026-11-03).
    """
    name = re.sub(r"\s+", "", brief.shop_name)
    kept = [k for k in keywords if not name or name not in re.sub(r"\s+", "", k)]
    product = brief.product.strip()
    extra = (
        {
            "new_menu": [f"{product} 신메뉴", f"{product} 맛집"],
            "promotion": [f"{product} 할인", f"{product} 이벤트"],
            "intro": [f"{product} 가게", "동네 가게 소개"],
            "notice": ["가게 공지", "가게 소식"],
        }[brief.purpose]
        if product or brief.purpose == "notice"
        else []
    )
    for word in [*extra, "가게 홍보"]:
        if len(kept) >= 3:
            break
        if word not in kept:
            kept.append(word)
    return kept


def scene_media(
    inp: Input, scene_count: int, roles: list[str] | None = None, texts: list[str] | None = None
) -> list[str]:
    """장면에 넣을 내 사진. 소상공인 모드는 AI 그림을 쓰지 않아 사진을 돌려 모든 장면을 채운다.

    AI에게 음식·매장을 그리지 말라고 해도 '햇살 창가'에 음식과 가짜 간판을 그렸다 (2026-11-02).
    실제와 다른 그림은 손님을 속일 수 있어 규칙이 아니라 구조로 막는다.
    """
    media = inp.user_media
    if not is_ad(inp) or not media:
        return media
    role_photos = LISTING_PHOTOS if inp.mode == "listing" else ROLE_PHOTOS
    if not roles or not any(m in inp.media_kinds for m in media):
        return [media[i % len(media)] for i in range(scene_count)]
    # 장면 역할에 맞는 종류의 사진 중 덜 쓴 것을 고른다 (같은 사진이 이어 나오지 않게)
    used = dict.fromkeys(media, 0)
    out: list[str] = []
    for i in range(scene_count):
        prefer = role_photos.get(roles[i] if i < len(roles) else "", ())
        # 매물: 대사·장면 묘사가 말하는 공간의 사진을 먼저
        # (실측: '거실 통창' 대사에 방 사진이 붙었다)
        named = (
            spoken_space(texts[i]) if inp.mode == "listing" and texts and i < len(texts) else None
        )
        if named and any(inp.media_kinds.get(m) == named for m in media):
            prefer = (named,)
        pool = [m for m in media if inp.media_kinds.get(m) in prefer] or media
        last = out[-1] if out else None
        pick = min(pool, key=lambda m: (used[m], m == last, media.index(m)))
        used[pick] += 1
        out.append(pick)
    return out


# 장면 역할별로 먼저 쓰는 사진 종류 (없으면 아무 사진)
ROLE_PHOTOS: dict[str, tuple[str, ...]] = {
    "hook": ("menu",),
    "method": ("menu", "owner"),
    "payoff": ("owner", "menu"),
    "offer": ("menu",),
    "cta": ("shop", "menu"),
}
# 대사·장면 묘사에 나오는 공간 이름 → 사진 종류 (먼저 나온 말이 그 장면의 공간)
_SPACE_WORDS: tuple[tuple[str, str], ...] = (
    (r"거실|living", "living"),
    (r"주방|부엌|싱크|kitchen", "kitchen"),
    (r"욕실|화장실|샤워|bath", "bath"),
    (r"안방|침실|작은\s*방|방\s*(?:안|하나|두|세|내부)|bedroom|room", "room"),
    (r"창밖|전망|조망|view|window", "view"),
    (r"외관|단지|건물|입구|현관\s*밖|exterior|building", "exterior"),
    (r"평면도|구조도|floor\s*plan", "plan"),
)


def spoken_space(text: str) -> str | None:
    """장면 대사·묘사가 처음 말하는 공간의 사진 종류. 없으면 None."""
    best: tuple[int, str] | None = None
    for pattern, kind in _SPACE_WORDS:
        found = re.search(pattern, text, re.IGNORECASE)
        if found and (best is None or found.start() < best[0]):
            best = (found.start(), kind)
    return best[1] if best else None


# 매물: 첫 장면은 가장 좋은 공간, 설명은 실내, 가격은 거실, 마지막은 외관
LISTING_PHOTOS: dict[str, tuple[str, ...]] = {
    "hook": ("living", "view", "exterior"),
    "problem": ("room", "kitchen"),
    "method": ("living", "kitchen", "room", "bath", "plan"),
    "payoff": ("view", "living"),
    "reveal": ("view", "living"),
    "offer": ("living", "plan"),
    "cta": ("exterior", "living"),
}


# ── 매물 홍보 (docs/PLAN_LISTING.md) ───────────────────────
# 공인중개사법 제18조의2와 국토부 고시 「부당한 중개대상물 표시·광고행위의 유형 및 기준」(2023-542):
# 가격·면적·사진을 사실과 다르게, 입지·여건을 과장하거나 숨기면 부당한 광고다. 교통시설 거리는
# 직선거리가 아니라 도보 거리·시간으로. 그래서 가격·끝맺음 대사와 매물 정보 카드는 입력값을
# 그대로 쓰고,
# 나머지 대사에는 입력에 없는 숫자·거리·과장 표현을 쓰지 못하게 한다.

_LISTING_BANNED = (
    r"최저가", r"급급매", r"초급매", r"급매", r"시세\s*(?:보다|이하)", r"실거래가보다",
    r"수익", r"투자", r"시세\s*차익", r"프리미엄", r"보장", r"확정(?!\s*일자)", r"호재",
    r"개발\s*예정",
    r"로열\s*층", r"초?역세권", r"학세권", r"숲세권", r"슬세권", r"직선\s*거리",
    r"대박", r"마지막\s*기회", r"놓치면", r"유일", r"최고(?!층)", r"최상(?!층)", r"완벽",
    r"인기(?!척)", r"문의\s*(?:폭주|쇄도)", r"서두르", r"곧\s*나갈", r"빨리\s*나가",
    r"\d+\s*(?:m|미터|km|킬로)\b", r"(?:바로|코)\s*앞", r"엎어지면",
    r"신축급", r"풀\s*옵션", r"올\s*수리", r"리모델링", r"확장",
    # 권리·금융·가격 평가·개발·옵션: 확인 없이 말하면 기만·과장 광고가 된다
    r"융자", r"대출", r"보증\s*보험", r"안심", r"근저당", r"압류", r"전세\s*사기", r"깡통",
    r"허위\s*매물", r"실\s*매물", r"저렴", r"(?<![감러워])싸(?=[게고요다서])", r"가성비", r"수수료",
    r"재건축", r"재개발", r"옵션", r"완비", r"가격\s*(?:조정|협의|절충)",
)  # fmt: skip

# 틀렸다고 단정할 수 없는 상태 표현. 다시 쓰게 하지 않고 중개사님께 보여 준다
_LISTING_SOFT = (
    r"넓", r"채광", r"햇[빛볕살]", r"조용", r"깨끗", r"깔끔", r"탁\s*트인", r"전망",
    r"아늑", r"쾌적", r"편리", r"가까", r"좋은", r"훌륭", r"환한", r"밝은",
    r"아기자기", r"꼼꼼", r"단정", r"관리(?:가|되|돼|도)",
)  # fmt: skip


# 대본이 입력 없이 말하면 안 되는 입지·시설 말 (국토부 고시 2023-542 제6조②: 입지·교통 과장).
# 장점·주변·소재지·단지 칸에 있을 때만 쓸 수 있다
_PLACES = (
    r"지하철", r"전철", r"정류장", r"버스", r"초등학교", r"중학교", r"고등학교", r"학교", r"학군",
    # '전세 시장'·'스마트 도어락'은 시설이 아니다
    r"학원가", r"유치원", r"어린이집", r"(?<!스)마트", r"편의점", r"백화점", r"재래\s*시장",
    r"상권", r"공원",
    r"병원", r"한강", r"[가-힣]*뷰", r"대단지", r"카페\s*거리", r"산책로", r"숲",
    # '○○역': 지역·영역·구역·역시는 빼고, 역 뒤가 조사·공백·문장 끝일 때만
    r"[가-힣]*[가-힣](?<![지영구무])역(?=$|\s|[.,!?]|까지|에서|이랑|으로|이|에|은|도|과|의|을)",
)  # fmt: skip
_DIRECTION = re.compile(r"(?:정)?[동서남북]{1,2}향")
# 한글로 쓴 수와 단위 ("방이 네 개", "삼십오 평", "오 분 거리").
# '두 분'(사람)은 고유어라 분을 빼고 본다
_KOREAN_COUNT = re.compile(
    # 고유어 수 + 층은 '한층 더 밝아요'와 겹쳐 뺀다
    r"(?<![가-힣])(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무|서른|마흔|쉰)\s*(?:개|칸|평|정거장|룸)"
    # 한자어 수: 평·억은 붙여 써도, 분·층은 띄어 쓸 때만 ('구분'·'이층' 같은 말을 잡지 않게)
    r"|(?<![가-힣])[일이삼사오육칠팔구십백]+\s*(?:평|억|정거장)"
    r"|(?<![가-힣])[일이삼사오육칠팔구십]+\s+(?:분|층)"  # 이층 구조·구분 같은 말은 붙여 쓴다
)


def listing_claims(text: str, lb: ListingBrief) -> list[str]:
    """매물 대사의 입지·방향·한글 숫자 주장 중 입력에 없는 것."""
    # 가격·입주·할 일·사무소 이름은 코드가 넣는 가격·연락 대사에 그대로 나온다 ('한강공인중개사')
    fields = (lb.location, lb.complex_name, lb.highlights, lb.nearby, lb.price, lb.move_in,
              lb.action, lb.office_name)  # fmt: skip
    allowed = unicodedata.normalize("NFKC", " ".join(fields)).replace(" ", "")
    out: list[str] = []
    for pattern in _PLACES:
        for found in re.findall(pattern, text):
            if found.replace(" ", "") not in allowed:
                out.append(found)
    direction = lb.direction.replace(" ", "")
    for found in _DIRECTION.findall(text):
        if found not in direction:  # 고시 제6조②: 방향을 사실과 다르게
            out.append(found)
    for found in _KOREAN_COUNT.findall(text):
        if found.replace(" ", "") not in allowed:
            out.append(found)
    return out


def live_fact_words(inp: Input | None, strategy) -> list[str]:
    """지금 대사·제목에 남아 있는 사실·상태 경고 말. 다듬기에서 고친 대사도 바로 다시 본다."""
    brief = ad_brief(inp) if inp else None
    if brief is None or strategy is None:
        return []
    texts = [*strategy.titles, *(s.line for s in strategy.scenes if s.role not in ("offer", "cta"))]
    return list(dict.fromkeys([*fact_words(texts, brief), *taste_words(texts, brief)]))


def listing_block(lb: ListingBrief) -> str:
    """LLM에 넘기는 매물 정보. 대사의 근거는 여기뿐이다."""
    fields = {
        "종류": PROPERTY_LABEL[lb.prop_type],
        "거래": DEAL_LABEL[lb.deal],
        "소재지(공개 범위)": lb.location,
        "단지·건물": lb.complex_name,
        "장점(중개사가 쓴 것)": lb.highlights,
        "주변(도보 기준)": lb.nearby,
        "손님이 할 일": lb.action,
    }
    lines = [f"- {k}: {v}" for k, v in fields.items() if v]
    return (
        "\n\n[매물 정보] 여기 있는 사실만 쓴다. 가격·면적·층·관리비는 대사에 쓰지 않는다"
        "(프로그램이 넣는다)\n" + "\n".join(lines)
    )


def price_line(lb: ListingBrief) -> str:
    """가격 장면 대사: 거래 형태 + 의뢰받은 가격 그대로 (+ 입주 가능일)."""
    price = _spoken(re.sub(r"\s*/\s*", ", ", lb.price))
    head = f"{DEAL_LABEL[lb.deal]} {price}"
    move = _spoken(lb.move_in)
    if not move:
        return f"{head}."
    return f"{head}. 입주는 {move} 가능해요."


def fix_listing_lines(scenes: list[Scene], lb: ListingBrief) -> list[Scene]:
    """가격 장면(role=offer)과 마지막 장면은 입력값으로 넣는다."""
    out = list(scenes)
    action = _spoken(lb.action) or f"{_spoken(lb.office_name)}에 연락 주세요"
    out[-1] = out[-1].model_copy(update={"role": "cta", "line": action + "."})
    free = [i for i, s in enumerate(out[:-1]) if i and s.role != "payoff"] or [len(out) - 2]
    spot = next((i for i, s in enumerate(out[1:-1], 1) if s.role == "offer"), free[-1])
    out[spot] = out[spot].model_copy(update={"role": "offer", "line": price_line(lb)})
    return out


def listing_info(lb: ListingBrief) -> tuple[str, ...]:
    """명시 의무 항목 (영상 끝 카드와 설명란에 같은 내용). 입력 원문 그대로."""
    place = " ".join(v for v in (lb.location.strip(), lb.complex_name.strip()) if v)
    office = f"{lb.office_name.strip()} · 대표 {lb.agent_name.strip()}"
    lines = (
        f"{PROPERTY_LABEL[lb.prop_type]} {DEAL_LABEL[lb.deal]} {lb.price.strip()}",
        place,
        f"{lb.area.strip()} · {lb.floor.strip()} · {lb.direction.strip()}",
        f"{lb.rooms.strip()} · 주차 {lb.parking.strip()}",
        f"사용승인 {lb.approved.strip()} · 입주 {lb.move_in.strip()}",
        f"관리비 {lb.maint_fee.strip()}",
        office,
        f"등록번호 {lb.reg_no.strip()}" if lb.reg_no.strip() else "",
        f"{lb.office_address.strip()} · {lb.office_phone.strip()}",
    )
    return tuple(line for line in lines if line.strip(" ·"))


def listing_card(lb: ListingBrief) -> EndCard:
    """영상 끝 매물 정보 카드. 명시 항목을 빠짐없이, 읽을 수 있는 크기와 시간으로 띄운다
    (고시 제7조: 중요한 내용을 지나치게 작은 글씨로 표기하면 기만적인 광고)."""
    return EndCard(title=lb.office_name.strip(), info=listing_info(lb))


def listing_checklist(lb: ListingBrief) -> list[dict]:
    """매물 영상 업로드 전 확인 (부당한 표시·광고 고시 기준)."""
    return [
        {
            "id": "listing_facts",
            "title": "매물 정보가 의뢰·공부상 내용과 같다",
            "text": "끝 화면과 설명란의 매물 정보(가격·면적·층·방향·관리비 등)가 의뢰받은 내용, "
            "공부상 면적과 같다",
            "auto": False,
        },
        {
            "id": "listing_available",
            "title": "지금 거래할 수 있는 의뢰 매물이다",
            "text": "지금 거래할 수 있는 매물이고, 매도인·임대인에게 광고를 의뢰받았다 "
            "(계약된 매물·없는 매물을 올리지 않는다)",
            "auto": False,
        },
        {
            "id": "listing_photos",
            "title": "이 매물의 실제 사진이고 개인정보가 없다",
            "text": "사진이 모두 이 매물의 실제 사진이다. 거주자 얼굴·우편물·차량 번호 같은 "
            "개인정보가 보이지 않는다",
            "auto": False,
        },
        {
            "id": "listing_lines",
            "title": "대사에 과장이 없고 거리는 도보 기준이다",
            "text": "대사를 직접 읽어 봤다. 입지·옵션·전망을 과장하지 않았고, "
            "거리는 도보 거리·시간이다 "
            "(AI가 쓴 글이다)",
            "auto": False,
        },
        {
            "id": "listing_assistant",
            "title": "중개보조원 정보를 넣지 않았다",
            "text": "중개보조원의 이름·연락처를 대사·화면·설명란에 넣지 않았다",
            "auto": False,
        },
        {
            "id": "listing_takedown",
            "title": "계약이 되면 영상을 바로 내린다",
            "text": "계약이 되면 이 영상을 바로 내리거나 비공개로 바꾼다",
            "auto": False,
        },
    ]


def listing_description(lb: ListingBrief) -> list[str]:
    """설명란의 매물 정보. 영상 끝 카드와 같은 내용을 글로 남긴다."""
    return list(listing_info(lb))


def listing_keywords(keywords: list[str], lb: ListingBrief) -> list[str]:
    """단지·사무소 이름이 든 검색어를 빼고, 종류·거래 형태 중심 검색어로 채운다."""
    names = [re.sub(r"\s+", "", n) for n in (lb.complex_name, lb.office_name) if n.strip()]
    kept = [k for k in keywords if not any(n in re.sub(r"\s+", "", k) for n in names)]
    kind, deal = PROPERTY_LABEL[lb.prop_type], DEAL_LABEL[lb.deal]
    for word in (f"{kind} {deal} 매물", f"{kind} 랜선 집들이", "매물 소개 영상"):
        if len(kept) >= 3:
            break
        if word not in kept:
            kept.append(word)
    return kept
