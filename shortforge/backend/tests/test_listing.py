"""매물 홍보 모드 (docs/PLAN_LISTING.md)."""

import httpx
import pytest
from pydantic import ValidationError

from app import modes, offices
from app.adapters.base import EndCard
from app.adapters.fake import FakeVideoGen
from app.adapters.video.ffmpeg import FFmpegRenderer
from app.config import Settings
from app.llm import load_prompt
from app.main import create_app
from app.publish import publish_kit
from app.schemas.project import Input, ListingBrief, Scene


def listing(**kw):
    base = {
        "office_name": "상동 행복공인중개사사무소",
        "office_address": "부천시 상동 123",
        "office_phone": "032-123-4567",
        "agent_name": "홍길동",
        "reg_no": "41190-2020-00012",
        "prop_type": "apartment",
        "deal": "jeonse",
        "price": "3억 2천만원",
        "location": "부천시 상동",
        "complex_name": "푸른마을",
        "area": "전용 84.9㎡",
        "floor": "7층 / 15층",
        "direction": "거실 기준 남향",
        "rooms": "방 3 · 욕실 2",
        "approved": "2015.03",
        "move_in": "즉시",
        "parking": "세대당 1대",
        "maint_fee": "월 15만원",
        "highlights": "거실 통창, 2024년 도배",
        "nearby": "상동역 도보 8분",
        "action": "문자로 방문 예약해 주세요",
    }
    return ListingBrief(**{**base, **kw})


def listing_input():
    return Input(topic="", mode="listing", listing=listing(), user_media=["media/a.jpg"])


def with_photo(orch, inp):
    p = orch.create_project(inp)
    photo = orch.store.project_dir(p.id) / "media" / "a.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"\xff\xd8\xff")
    return p


@pytest.fixture
async def client(orch, store):
    app = create_app(Settings(_env_file=None, data_dir=store.data_dir), orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def test_topic_comes_from_the_listing_and_brief_is_required():
    inp = listing_input()
    assert inp.topic == "부천시 상동 푸른마을 아파트 전세 매물 소개"
    with pytest.raises(ValidationError):
        Input(topic="x", mode="listing")
    with pytest.raises(ValidationError):  # 명시 의무 항목은 비울 수 없다
        listing(maint_fee="")
    with pytest.raises(ValidationError):  # 등록번호도 명시 항목이다
        listing(reg_no="")


def test_price_and_closing_lines_are_the_input_as_is():
    scenes = [
        Scene(id=f"S{i}", start=i * 5, end=i * 5 + 5, role=r, line="AI가 쓴 말", visual="v")
        for i, r in enumerate(["hook", "method", "method", "payoff", "offer", "cta"])
    ]
    out = modes.fix_shop_lines(scenes, listing())
    assert out[4].line == "전세 3억 2천만원. 입주는 즉시 가능해요." and out[4].role == "offer"
    assert out[-1].line == "문자로 방문 예약해 주세요." and out[-1].role == "cta"
    assert [s.line for s in out[:4]] == ["AI가 쓴 말"] * 4


def test_lines_cannot_add_numbers_or_hype_missing_from_the_input():
    lb = listing()
    bad = modes.fact_problems(
        ["역세권 급매예요", "역까지 300m", "도보 3분이면 마트", "투자 가치도 좋아요"], lb
    )
    words = " ".join(bad)
    for w in ("역세권", "급매", "300", "3분", "투자"):
        assert w in words
    # 입력에 있는 사실은 그대로 쓸 수 있다
    assert modes.fact_problems(["상동역까지 도보 8분이에요", "거실 통창이 있어요"], lb) == []
    # 상태 평가는 단정할 수 없어 경고로만 보여 준다
    assert modes.taste_problems(["거실이 넓고 채광이 좋아요"], lb)


def test_info_card_lists_the_required_items_and_no_assistant():
    lb = listing()
    info = modes.listing_info(lb)
    text = " ".join(info)
    for item in ("아파트 전세 3억 2천만원", "전용 84.9㎡", "7층 / 15층", "거실 기준 남향",
                 "방 3 · 욕실 2", "주차 세대당 1대", "사용승인 2015.03", "입주 즉시",
                 "관리비 월 15만원", "대표 홍길동", "등록번호 41190-2020-00012",
                 "032-123-4567"):  # fmt: skip
        assert item in text, item
    card = modes.end_card(listing_input())
    assert card == EndCard(title=lb.office_name, info=info)
    cues = FFmpegRenderer()._overlays([], 30.0, card)
    assert [c.style for c in cues] == ["dim", "card_head", "card_info"]
    assert cues[0].start == pytest.approx(30.0 - 4.5)  # 줄이 많아 더 오래 띄운다


def test_everyday_listing_words_are_not_flagged():
    """사실 안내·일상어를 과장으로 잡으면 4단계를 헛되이 다시 만든다 (검토에서 찾은 오탐)."""
    lb = listing()
    ok = [
        "전입신고와 확정일자 모두 가능해요",
        "최상층이라 위층 소음이 없어요",
        "인기척 없이 조용해요",
    ]
    assert [
        p for p in modes.fact_problems(ok, lb) if "확정" in p or "최상" in p or "인기" in p
    ] == []
    # 사무소 주소·전화의 숫자로 대사의 숫자가 통과하지 않는다
    assert modes.fact_problems(["123동이라 조용해요"], lb)
    assert modes.fact_problems(["보세요"], lb) == []


def test_monthly_price_is_spoken_without_slash_and_offer_never_takes_the_hook():
    lb = listing(deal="monthly", price="보증금 500만원 / 월 45만원", move_in="12월 1일")
    assert modes.price_line(lb) == "월세 보증금 500만원, 월 45만원. 입주는 12월 1일 가능해요."
    scenes = [
        Scene(id=f"S{i}", start=i * 5, end=i * 5 + 5, role=r, line="AI", visual="v")
        for i, r in enumerate(["offer", "method", "method", "payoff", "cta"])
    ]
    out = modes.fix_shop_lines(scenes, listing(action=""))
    assert out[0].line == "AI"  # 첫 장면(훅)은 가격으로 덮지 않는다
    assert out[-1].line == "상동 행복공인중개사사무소에 연락 주세요."


def test_card_hides_spoken_captions_while_it_is_on_screen():
    from app.adapters.video.ffmpeg import INFO_CARD_SEC, before_card
    from app.subtitles import Cue

    cues = [Cue(0, 5, "a", "body"), Cue(24, 27, "b", "body"), Cue(27, 30, "c", "body")]
    card = modes.listing_card(listing())
    kept = before_card(cues, 30.0, card)
    assert [c.text for c in kept] == ["a", "b"] and kept[-1].end == pytest.approx(
        30 - INFO_CARD_SEC
    )
    assert before_card(cues, 30.0, None) == cues  # 가게·취미는 그대로


def test_second_scene_does_not_repeat_the_hook():
    from app.steps.s4_strategy import drop_repeated_hook

    def sc(i, line):
        return Scene(id=f"S{i}", start=i * 5, end=i * 5 + 5, role="method", line=line, visual="v")

    scenes = [
        sc(0, "상동역 걸어서 가까운 곳이에요."),
        sc(1, "상동역 걸어서 가까운 곳이에요. 안으로 들어가서 공간을 보여드릴게요."),
        sc(2, "거실이에요."),
    ]
    out = drop_repeated_hook(scenes)
    assert out[1].line == "안으로 들어가서 공간을 보여드릴게요." and out[0].line == scenes[0].line
    same = [scenes[0], sc(1, "상동역 걸어서 가까운 곳이에요!"), scenes[2]]
    assert drop_repeated_hook(same) == same  # 남는 말이 없으면 그대로
    # 입력값으로 넣은 가격 대사는 자르지 않는다
    line = "전세 3억 1천만원. 입주는 즉시 가능해요."
    price = Scene(id="S1", start=5, end=10, role="offer", line=line, visual="v")
    hooked = [sc(0, "전세 3억"), price, scenes[2]]
    assert drop_repeated_hook(hooked) == hooked
    # 어절 중간에서는 자르지 않는다
    mid = [sc(0, "월세 50"), sc(1, "월세 500만원짜리 방이에요."), scenes[2]]
    assert drop_repeated_hook(mid) == mid
    short = [sc(0, "와!"), sc(1, "와! 넓어요."), scenes[2]]
    assert drop_repeated_hook(short) == short  # 너무 짧은 훅은 보지 않는다


async def test_listing_info_edit_only_redoes_the_script(orch):
    """가격 오타를 고치면 검색·분석은 그대로 두고 4단계(대본)부터 다시 한다."""
    p = with_photo(orch, listing_input())
    await orch.run_all(p.id, to_step="s6")
    saved = orch.store.load(p.id)
    fixed = saved.input.model_copy(update={"listing": listing(price="3억 1천만원")})
    p = await orch.edit(p.id, "input", fixed)
    assert [p.status[s] for s in ("s1", "s2", "s3")] == ["done"] * 3
    assert p.status["s4"] == "stale"
    p = await orch.run_all(p.id, "s4", to_step="s6")
    assert "전세 3억 1천만원. 입주는 즉시 가능해요." in [s.line for s in p.strategy.scenes]


def test_keywords_drop_complex_and_office_names():
    kept = modes.listing_keywords(["푸른마을 전세", "상동 아파트 전세"], listing())
    assert "푸른마을 전세" not in kept and "상동 아파트 전세" in kept and len(kept) == 3


def test_listing_prompt_has_a_version():
    assert load_prompt("s4_listing").version


async def test_listing_runs_to_render_with_card_and_checklist(orch):
    p = with_photo(orch, listing_input())
    await orch.run_all(p.id, to_step="s7")
    saved = orch.store.load(p.id)
    assert saved.status["s7"] == "done", saved.errors
    lines = [s.line for s in saved.strategy.scenes]
    assert "전세 3억 2천만원. 입주는 즉시 가능해요." in lines
    assert lines[-1] == "문자로 방문 예약해 주세요."
    assert all(a.image.source == "user" for a in saved.assets)  # 실제 사진만
    kit = publish_kit(saved)
    ids = [c["id"] for c in kit["checklist"]]
    for i in ("listing_facts", "listing_available", "listing_photos", "listing_takedown"):
        assert i in ids
    assert "등록번호 41190-2020-00012" in kit["description"]
    assert "푸른마을" not in "".join(t for t in kit["description"].split() if t.startswith("#"))


async def test_listing_refuses_ai_pictures_and_ai_video(client, orch):
    orch.adapters.video_gen = FakeVideoGen()
    p = with_photo(orch, listing_input())
    await orch.run_all(p.id, to_step="s6")
    scene = orch.store.load(p.id).assets[0].scene_id
    r = await client.post(f"/projects/{p.id}/scenes/{scene}/image")
    assert r.status_code == 409 and "실제 사진" in r.json()["detail"]
    r = await client.post(f"/projects/{p.id}/scenes/{scene}/motion?photo_ok=true")
    assert r.status_code == 409 and "움직이지 않아요" in r.json()["detail"]


async def test_mode_and_listing_cannot_be_changed_by_patching(client, orch):
    p = with_photo(orch, listing_input())
    edited = orch.store.load(p.id).input.model_dump(mode="json")
    edited.update({"mode": "hobby", "listing": None, "topic": "아무 주제"})
    r = await client.patch(f"/projects/{p.id}/input", json=edited)
    assert r.status_code == 200
    saved = orch.store.load(p.id).input
    assert saved.mode == "listing" and saved.listing is not None


async def test_offices_are_saved_and_listing_menu_toggles(client, store):
    office = {k: v for k, v in listing().model_dump().items() if k in offices.Office.model_fields}
    r = await client.post("/offices", json=office)
    assert r.status_code == 200 and r.json()[0]["office_name"] == "상동 행복공인중개사사무소"
    assert (await client.get("/offices")).json()[0]["agent_name"] == "홍길동"
    assert "assistant" not in offices.Office.model_fields  # 중개보조원 칸은 없다
