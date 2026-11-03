"""취미·소상공인 모드 (D21)."""

import httpx
import pytest
from pydantic import ValidationError

from app import modes, shops
from app.adapters.fake import FakeVideoGen
from app.config import Settings
from app.llm import load_prompt
from app.main import create_app
from app.publish import publish_kit
from app.schemas.project import BusinessBrief, Input, Scene
from app.steps.s4_strategy import concept_basis, retry_kind
from app.steps.s5_prompts import tts_script


def brief(**kw):
    base = {
        "shop_name": "소담 분식",
        "area": "부천 상동",
        "purpose": "promotion",
        "product": "김치볶음밥",
        "offer": "평일 점심 1,000원 할인",
        "period": "11월 말까지",
        "action": "네이버 지도에서 찾아 주세요",
    }
    return BusinessBrief(**{**base, **kw})


def test_hobby_is_the_default_and_keeps_old_projects_working():
    inp = Input.model_validate({"topic": "홈트"})
    assert inp.mode == "hobby"
    assert inp.business is None
    assert modes.business_block(inp) == ""
    assert modes.profile_for(inp) is modes.HOBBY


def test_hobby_still_needs_a_topic():
    with pytest.raises(ValidationError):
        Input(topic="")


def test_business_builds_its_topic_from_the_shop():
    inp = Input(topic="", mode="business", business=brief())
    assert "소담 분식" in inp.topic and "김치볶음밥" in inp.topic
    assert inp.model_copy(update={"voice": "male"}).topic == inp.topic


def test_business_needs_shop_details():
    with pytest.raises(ValidationError):
        Input(topic="", mode="business")


def test_input_survives_being_saved_and_loaded():
    inp = Input(topic="", mode="business", business=brief())
    assert Input.model_validate_json(inp.model_dump_json()) == inp


def test_business_skips_overseas_search():
    settings = Settings(_env_file=None)
    hobby = Input(topic="홈트")
    business = Input(topic="", mode="business", business=brief())
    assert modes.markets(settings, hobby) == settings.markets
    assert modes.markets(settings, business) == []


def test_block_only_lists_what_was_given():
    inp = Input(topic="", mode="business", business=brief(purpose="intro", offer="", period=""))
    block = modes.business_block(inp)
    assert "소담 분식" in block and "혜택" not in block and "기간" not in block


@pytest.mark.parametrize(
    "line",
    [
        "평일 점심 1,000원 할인해 드려요",
        "1000원 할인이에요",
        "11월 말까지예요",
        "부천 상동 소담 분식이에요",
        "이 프로모션 놓치지 마세요",
        "오늘 원하는 메뉴를 골라 보세요",
        "무료한 점심에 오세요",
        "오늘만큼은 편하게 오세요",
        "전통시장 옆에 있어요",
        "이 원재료로 만들어요",
    ],
)
def test_facts_from_the_input_pass(line):
    assert modes.fact_problems([line], brief()) == []


@pytest.mark.parametrize(
    "line",
    [
        "지금 2,000원 할인해요",
        "지금 5,000원인데 오세요",
        "5,000원하는 메뉴",
        "이번 주 50% 할인",
        "50프로예요",
        "오천원에 드려요",
        "오백 원 할인해요",
        "구천구백 원이에요",
        "₩5,000 할인",
        "오늘 1+1 행사해요",
        "1,500원이에요",
        "５０％ 할인",
        "12월까지 해요",
        "이번 달 25일까지 할인해요",
        "11월 3일까지예요",
        "점심 1시까지 오세요",
        "하루 300그릇 팔려요",
        "평점 4.9예요",
        "오늘만 드려요",
        "동네 최고 맛집이에요",
        "다이어트에도 좋아요",
        "1위 맛집이에요",
        "동네 1위입니다",
        "이 동네 일등이에요",
        "삼십 년 전통이에요",
        "손님들이 줄 서서 먹어요",
        "점심마다 이 골목이 난리예요",
        "많은 분들이 찾아 주세요",
        "찾으시는 분들이 많더라고요",
        "사람들이 이 가게로 모이는 이유",
        "매일 직접 반죽해요",
        "재료는 모두 국내산이에요",
        "절반 가격이에요",
        "튀김을 덤으로 드려요",
    ],
)
def test_made_up_facts_are_caught(line):
    assert modes.fact_problems([line], brief()) != [], line


@pytest.mark.parametrize(
    "line",
    [
        "11일까지 할인해요",
        "11월 11일까지 할인해요",
        "1,000명이 찾았어요",
        "1,000그릇 팔렸어요",
        "오천원인데 오세요",
        "오천 원으로 드세요",
        "단돈오천원",
        "천 원만 내세요",
        "내일까지 드려요",
        "이번 주말까지 드려요",
        "이십오일까지 드려요",
    ],
)
def test_same_number_with_another_meaning_is_caught(line):
    assert modes.fact_problems([line], brief()) != [], line


def test_conditions_in_brackets_stay_in_the_spoken_line():
    line = modes.offer_line(brief(offer="음료 무료 (평일 점심만)", period="11/1~11/30"))
    assert tts_script(line) == line or "평일 점심만" in tts_script(line)
    assert "부터" in line and "(" not in line


def test_period_alone_gets_a_scene():
    out = modes.fix_shop_lines(
        scenes("hook", "method", "method", "method", "cta"),
        brief(purpose="new_menu", offer="", period="11월 말까지"),
    )
    assert out[3].role == "offer" and out[3].line == "11월 말까지."


def test_notice_says_its_content_exactly():
    b = brief(purpose="notice", product="12월 25일 쉬어요", offer="", period="")
    assert modes.offer_line(b) == "12월 25일 쉬어요."


def test_pride_scene_is_not_replaced_by_the_offer():
    out = modes.fix_shop_lines(scenes("hook", "method", "method", "payoff", "cta"), brief())
    assert out[3].role == "payoff" and out[2].role == "offer"


async def test_long_offer_does_not_waste_the_daily_limit(orch):
    seen = spy(orch)
    long_brief = brief(offer=("평일 점심 1,000원 할인 " * 7)[:80], period="11월 말까지")
    p = orch.create_project(Input(topic="", mode="business", business=long_brief))
    await orch.run_all(p.id, to_step="s4")
    assert [t for t, _, _ in seen].count("s4_strategy") == 1


def test_only_numbers_from_the_input_are_allowed():
    assert modes.fact_problems(["5천원 할인해요"], brief(offer="1천원 할인")) != []
    assert modes.fact_problems(["10만원 할인해요"], brief(offer="1만원 할인")) != []


def test_pride_is_the_only_source_of_boasting():
    good = brief(pride="매일 직접 반죽해요")
    assert modes.fact_problems(["매일 직접 반죽해요"], good) == []


def test_offer_words_need_an_offer():
    assert modes.fact_problems(["오늘 할인해요"], brief(purpose="intro", offer="")) != []


def test_promotion_needs_an_offer():
    with pytest.raises(ValidationError):
        brief(offer="")


@pytest.mark.parametrize("line", ["서비스가 좋아요", "덤덤하게 말해요", "최고기온이 올라요"])
def test_ordinary_words_are_not_treated_as_offers(line):
    assert modes.fact_problems([line], brief(purpose="intro", offer="")) == []


def scenes(*roles):
    return [
        Scene(id=f"S{i + 1}", role=r, start=i, end=i + 1, line="AI가 쓴 말", visual="v")
        for i, r in enumerate(roles)
    ]


def test_offer_and_ending_are_never_written_by_the_ai():
    out = modes.fix_shop_lines(scenes("hook", "method", "offer", "method", "payoff"), brief())
    assert out[2].line == "평일 점심 1,000원 할인! 11월 말까지."
    assert out[-1].line == "네이버 지도에서 찾아 주세요."
    assert out[-1].role == "cta"
    assert out[0].line == out[1].line == "AI가 쓴 말"


def test_missing_offer_scene_is_created_before_the_ending():
    out = modes.fix_shop_lines(scenes("hook", "method", "method", "method", "cta"), brief())
    assert out[3].role == "offer"
    assert "1,000원" in out[3].line


def test_no_offer_means_no_offer_scene():
    out = modes.fix_shop_lines(
        scenes("hook", "method", "method", "method", "cta"),
        brief(purpose="intro", offer="", period=""),
    )
    assert all(s.role != "offer" for s in out)


def test_fact_retry_is_labeled():
    assert retry_kind(f"{modes.FACT_PREFIX}: '5'") == "facts"


def test_photos_fill_every_scene_only_in_business_mode():
    media = ["a.jpg", "b.jpg"]
    hobby = Input(topic="홈트", user_media=media)
    business = Input(topic="", mode="business", business=brief(), user_media=media)
    assert modes.scene_media(hobby, 5) == media
    assert modes.scene_media(business, 5) == ["a.jpg", "b.jpg", "a.jpg", "b.jpg", "a.jpg"]


def test_shops_remember_the_latest_first(tmp_path):
    assert shops.load(tmp_path) == []
    shops.save(tmp_path, shops.Shop(shop_name="가", area="1"))
    shops.save(tmp_path, shops.Shop(shop_name="나"))
    saved = shops.save(tmp_path, shops.Shop(shop_name="가", area="2"))
    assert [s.shop_name for s in saved] == ["가", "나"]
    assert shops.load(tmp_path)[0].area == "2"


def test_broken_shop_file_starts_fresh(tmp_path):
    (tmp_path / "shops.json").write_text("{깨짐", encoding="utf-8")
    assert shops.load(tmp_path) == []


@pytest.fixture
async def client(orch, store):
    app = create_app(Settings(_env_file=None, data_dir=store.data_dir), orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def business_input():
    return Input(topic="", mode="business", business=brief(), user_media=["media/a.jpg"])


def with_photo(orch, inp):
    p = orch.create_project(inp)
    photo = orch.store.project_dir(p.id) / "media" / "a.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"\xff\xd8\xff")
    return p


async def test_api_builds_the_topic(client):
    r = await client.post(
        "/projects",
        json={"topic": "", "mode": "business", "business": brief().model_dump()},
    )
    assert r.status_code == 201
    assert "소담 분식" in r.json()["input"]["topic"]


async def test_business_uses_only_real_photos(orch):
    p = with_photo(orch, business_input())
    await orch.run_all(p.id, to_step="s6")
    saved = orch.store.load(p.id)
    assert saved.status["s6"] == "done", saved.errors
    assert saved.input.world_keywords == []
    assert {a.image.source for a in saved.assets} == {"user"}
    assert saved.strategy.scenes[-1].role == "cta"


async def test_scene_photo_survives_rebuilding_assets(client, orch):
    p = with_photo(orch, business_input())
    await orch.run_all(p.id, to_step="s6")
    swap = orch.store.project_dir(p.id) / "media" / "swap.jpg"
    swap.write_bytes(b"\xff\xd8\xff")
    scene = orch.store.load(p.id).assets[2].scene_id
    r = await client.post(f"/projects/{p.id}/scenes/{scene}/photo", json={"path": "media/swap.jpg"})
    assert r.status_code == 200
    inp = orch.store.load(p.id).input.model_copy(update={"voice": "male"})
    await orch.edit(p.id, "input", inp)
    await orch.run_all(p.id, "s5", to_step="s6")
    saved = orch.store.load(p.id).assets
    assert saved[2].image.path == "media/swap.jpg"
    assert saved[1].image.path == "media/a.jpg"  # 다른 장면으로 번지지 않는다


async def test_hashtags_do_not_carry_claims(orch):
    p = with_photo(orch, business_input())
    await orch.run_all(p.id, to_step="s6")
    saved = orch.store.load(p.id)
    saved.input = saved.input.model_copy(update={"keywords": ["부천 맛집", "상동 분식"]})
    description = publish_kit(saved)["description"]
    assert "#상동분식" in description and "맛집" not in description


async def test_business_without_photos_explains_what_is_needed(orch):
    p = orch.create_project(Input(topic="", mode="business", business=brief()))
    await orch.run_all(p.id, to_step="s5")
    assert "사진" in orch.store.load(p.id).errors["s5"]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("image", None),
        ("candidates", None),
        ("videos", None),
        ("motion", None),
        ("video/select", {"id": 1}),
        ("image/select", {"prompt": "p", "path": "assets/candidates/x.jpg"}),
    ],
)
async def test_ai_pictures_are_refused_for_shops(client, orch, path, body):
    orch.adapters.video_gen = FakeVideoGen()
    p = with_photo(orch, business_input())
    await orch.run_all(p.id, to_step="s6")
    scene = orch.store.load(p.id).assets[0].scene_id
    r = await client.post(f"/projects/{p.id}/scenes/{scene}/{path}", json=body)
    assert r.status_code == 409
    assert "실제 사진" in r.json()["detail"]


async def test_mode_cannot_be_changed_by_patching_input(client, orch):
    p = with_photo(orch, business_input())
    edited = orch.store.load(p.id).input.model_dump(mode="json")
    edited.update({"mode": "hobby", "business": None, "audience": "직장인"})
    r = await client.patch(f"/projects/{p.id}/input", json=edited)
    assert r.status_code == 200
    saved = orch.store.load(p.id).input
    assert saved.mode == "business" and saved.business is not None
    assert saved.audience == "직장인"


async def test_changed_offer_does_not_reuse_old_concepts():
    a = Input(topic="", mode="business", business=brief())
    b = Input(topic=a.topic, mode="business", business=brief(offer="평일 점심 2,000원 할인"))
    assert concept_basis(a, []) != concept_basis(b, [])


def spy(orch):
    seen = []
    real = orch.adapters.llm.generate_json

    async def generate_json(task, system, user, schema, **kw):
        seen.append((task, system, user))
        return await real(task, system, user, schema, **kw)

    orch.adapters.llm.generate_json = generate_json
    return seen


async def test_business_strategy_gets_the_shop_rules(orch):
    seen = spy(orch)
    p = orch.create_project(Input(topic="", mode="business", business=brief()))
    await orch.run_all(p.id, to_step="s4")
    system, user = next((s, u) for t, s, u in seen if t == "s4_strategy")
    assert "소상공인 가게 홍보" in system
    assert "평일 점심 1,000원 할인" in user
    concept_system = next(s for t, s, _ in seen if t == "s4_concepts")
    assert "소상공인 가게 홍보" in concept_system


async def test_hobby_prompts_stay_exactly_the_same(orch, sample_input):
    seen = spy(orch)
    p = orch.create_project(sample_input)
    await orch.run_all(p.id, to_step="s4")
    by_task = {t: (s, u) for t, s, u in seen}
    assert by_task["s4_strategy"][0] == load_prompt("s4_strategy").text
    assert by_task["s4_concepts"][0] == load_prompt("s4_concepts").text
    assert by_task["s1_keywords"][0] == load_prompt("s1_keywords").text
    assert all("[가게 정보]" not in u for _, _, u in seen)


async def test_invented_price_is_rejected_and_rewritten(orch):
    real = orch.adapters.llm._s4_strategy
    calls = []

    def bad_then_good(user):
        calls.append(1)
        out = real(user)
        if len(calls) == 1:
            out["scenes"][1]["line"] = "지금 오시면 5,000원에 드려요"
        return out

    orch.adapters.llm._s4_strategy = bad_then_good
    p = orch.create_project(Input(topic="", mode="business", business=brief()))
    await orch.run_all(p.id, to_step="s4")
    assert len(calls) == 2
    last = orch.store.load(p.id).strategy.scenes[-1]
    assert last.role == "cta" and last.line == f"{brief().action}."
    assert all("5,000" not in s.line for s in orch.store.load(p.id).strategy.scenes)


async def test_stubborn_invention_warns_instead_of_stopping(orch):
    real = orch.adapters.llm._s4_strategy

    def always_bad(user):
        out = real(user)
        out["scenes"][1]["line"] = "손님들이 줄 서서 드세요"
        return out

    orch.adapters.llm._s4_strategy = always_bad
    p = orch.create_project(Input(topic="", mode="business", business=brief()))
    await orch.run_all(p.id, to_step="s4")
    saved = orch.store.load(p.id)
    assert saved.status["s4"] == "done", saved.errors  # 막다른 길이 아니라 사장님이 고칠 수 있다
    assert any(w.startswith(modes.FACT_PREFIX) for w in saved.warnings["s4"])


async def test_lengthening_never_adds_to_a_shop_script(orch):
    seen = spy(orch)
    p = orch.create_project(Input(topic="", mode="business", business=brief()))
    await orch.run_all(p.id, to_step="s4")
    assert "s4_lengthen" not in [t for t, _, _ in seen]


async def test_settings_switch_rejects_other_sites(orch, store, tmp_path):
    settings = Settings(_env_file=None, data_dir=store.data_dir)
    app = create_app(settings, orch, env_path=tmp_path / ".env")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        evil = {"Origin": "https://evil.example"}
        assert (
            await c.post("/settings/business", json={"on": True}, headers=evil)
        ).status_code == 403
        assert (await c.post("/shops", json={"shop_name": "가"}, headers=evil)).status_code == 403
        assert (await c.post("/settings/business", json={"on": True})).json()["business_mode"]
        assert "BUSINESS_MODE=true" in (tmp_path / ".env").read_text(encoding="utf-8")


async def test_shop_api(client):
    assert (await client.get("/shops")).json() == []
    r = await client.post("/shops", json={"shop_name": "소담 분식", "area": "상동"})
    assert r.status_code == 200
    assert (await client.get("/shops")).json()[0]["shop_name"] == "소담 분식"


async def test_business_mode_is_off_by_default(client):
    assert (await client.get("/config")).json()["business_mode"] is False


def test_taste_words_are_only_flagged_when_not_in_the_input():
    b = brief(pride="매일 아침 볶는 고소한 참기름")
    lines = ["겉은 바삭하고 고소해요", "정말 바삭"]
    assert modes.taste_problems(lines, b) == [f"{modes.FACT_PREFIX}: '바삭'"]


def test_taste_word_forms():
    b = brief(pride="부드럽고 촉촉한 면")
    assert modes.taste_problems(["부드러운 면이에요"], b) == []
    plain = brief()
    assert modes.taste_problems(["부드럽게 넘어가요"], plain) == [
        f"{modes.FACT_PREFIX}: '부드럽게'"
    ]
    assert modes.taste_problems(["깊은맛"], plain) == [f"{modes.FACT_PREFIX}: '깊은맛'"]


def test_description_keeps_what_the_owner_wrote():
    b = brief(offer="[오픈기념] 1,000~2,000원 할인", period="11/1~11/30")
    assert modes.shop_description(b) == [
        "소담 분식 (부천 상동)",
        "[오픈기념] 1,000~2,000원 할인 · 11/1~11/30",
        "네이버 지도에서 찾아 주세요",
    ]


def test_description_without_offer():
    b = brief(purpose="intro", offer="", period="")
    assert modes.shop_description(b) == ["소담 분식 (부천 상동)", "네이버 지도에서 찾아 주세요"]
    notice = brief(purpose="notice", offer="", period="", product="이번 주 일요일 휴무")
    assert "이번 주 일요일 휴무" in modes.shop_description(notice)


async def test_hashtags_check_the_words_before_spaces_go(orch):
    p = with_photo(orch, business_input())
    await orch.run_all(p.id, to_step="s6")
    saved = orch.store.load(p.id)
    business = saved.input.business.model_copy(update={"shop_name": "★★★"})
    keywords = ["많은 분들이 찾는", "바삭한 돈까스", "상동 분식"]
    saved.input = saved.input.model_copy(update={"keywords": keywords, "business": business})
    text = publish_kit(saved)["description"]
    assert "많은분들이" not in text and "바삭한" not in text
    assert "#상동분식" in text and "# " not in text


def test_hobby_gets_no_shop_items(orch, sample_input):
    p = orch.create_project(sample_input)
    kit = publish_kit(p)
    assert not [c for c in kit["checklist"] if c["id"].startswith("shop_")]
    assert any("수익을 낼 거라면" in c["text"] for c in kit["checklist"])


async def test_shop_upload_kit(orch):
    p = with_photo(orch, business_input())
    await orch.run_all(p.id, to_step="s6")
    kit = publish_kit(orch.store.load(p.id))
    items = {c["id"]: c["text"] for c in kit["checklist"]}
    assert "평일 점심 1,000원 할인" in items["shop_facts"] and "11월 말까지" in items["shop_facts"]
    assert {"shop_lines", "shop_photos"} <= set(items)
    assert "손님·직원" in items["portrait"]
    assert "상업적 이용" in items["commercial"]
    text = kit["description"]
    assert "소담 분식 (부천 상동)" in text
    assert "평일 점심 1,000원 할인 · 11월 말까지" in text
    assert "네이버 지도에서 찾아 주세요" in text
    assert "#소담분식" in text and "#부천상동" in text
