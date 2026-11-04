"""가게 입력 확인(맞춤법·혜택 되묻기), 사진 종류, 흐린 배경 맞춤, AI 그림 점검, 그림 소스 통일."""

from pathlib import Path

import httpx
import pytest

from app import modes
from app.adapters.base import ImageAdapter, ImageQuotaExceeded, ImageResult
from app.adapters.fake import FakeLLM
from app.adapters.image.chain import ImageChain
from app.adapters.video.ffmpeg import _fit
from app.config import Settings
from app.image_check import check_images
from app.main import create_app
from app.schemas.project import Asset, BusinessBrief, ImageAsset, Input, VoiceAsset
from app.shop_check import Fix, ShopDraft, accept, offer_question, spelling


@pytest.fixture
async def client(orch, store):
    app = create_app(Settings(_env_file=None, data_dir=store.data_dir), orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── A. 입력 확인 ─────────────────────────────────────────


async def test_spelling_is_only_suggested(client):
    r = await client.post(
        "/shops/check",
        json={"shop_name": "소담분식", "product": "떡복기", "offer": "주말 특가"},
    )
    body = r.json()
    assert r.status_code == 200
    assert body["fixes"] == [
        {"field": "product", "original": "떡복기", "fixed": "떡볶이", "label": "상품"}
    ]
    assert "얼마나" in body["offer_question"]


def test_only_spelling_sized_fixes_pass():
    draft = ShopDraft(product="떡복기", offer="평일 점심 1,000원 할인", pride="확끈하게 매워요")
    assert accept(Fix(field="pride", original="확끈하게 매워요", fixed="화끈하게 매워요"), draft)
    # 숫자를 바꾸거나, 다시 쓰거나, 고유명사 칸을 건드리면 버린다
    more = Fix(field="offer", original=draft.offer, fixed="평일 점심 2,000원 할인")
    assert not accept(more, draft)
    assert not accept(
        Fix(field="product", original="떡복기", fixed="매콤달콤 국물 떡볶이 세트"), draft
    )
    assert not accept(Fix(field="shop_name", original="", fixed="x"), draft)
    assert not accept(Fix(field="product", original="다른 값", fixed="떡볶이"), draft)


async def test_check_never_blocks_when_the_ai_fails():
    class Broken(FakeLLM):
        async def generate_json(self, *a, **k):
            raise RuntimeError("down")

    assert await spelling(Broken(), ShopDraft(product="떡복기")) == []


@pytest.mark.parametrize(
    ("offer", "asks"),
    [
        ("주말 특가", True),
        ("1,000원 할인", False),
        ("음료 무료", False),
        ("반값", False),
        ("", False),
    ],
)
def test_vague_offer_gets_a_question(offer, asks):
    assert (offer_question(ShopDraft(offer=offer)) is not None) is asks


# ── B. 사진 종류 ─────────────────────────────────────────


def shop_input(kinds):
    media = list(kinds)
    return Input(
        topic="",
        mode="business",
        business=BusinessBrief(shop_name="소담 분식", product="떡볶이", action="오세요"),
        user_media=media,
        media_kinds={m: k for m, k in kinds.items() if k},
    )


def test_scenes_get_photos_that_fit_their_role():
    inp = shop_input({"media/dish.jpg": "menu", "media/door.jpg": "shop", "media/me.jpg": "owner"})
    roles = ["hook", "method", "payoff", "offer", "cta"]
    got = modes.scene_media(inp, 5, roles)
    assert got[0] == "media/dish.jpg" and got[-1] == "media/door.jpg"
    assert "media/me.jpg" in got[1:3]  # 상품·자랑 장면에 사장님 사진
    assert set(got) == set(inp.user_media)  # 올린 사진을 모두 쓴다
    # 종류를 고르지 않았으면 예전처럼 돌려 쓴다
    plain = shop_input({"media/a.jpg": None, "media/b.jpg": None})
    assert modes.scene_media(plain, 3, roles) == ["media/a.jpg", "media/b.jpg", "media/a.jpg"]


def test_script_knows_which_photos_exist():
    block = modes.business_block(shop_input({"media/dish.jpg": "menu"}))
    assert "[가진 사진] 메뉴·음식 1장" in block and "없음: 매장·간판, 사장님·조리 모습" in block
    unknown = modes.business_block(shop_input({"media/a.jpg": None}))
    assert "종류 모름 1장" in unknown and "없음" not in unknown


async def test_upload_keeps_photo_kinds(client, orch):
    r = await client.post("/projects", json={"topic": "홈트"})
    pid = r.json()["id"]
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    r = await client.post(
        f"/projects/{pid}/media",
        files=[("files", ("a.jpg", jpg, "image/jpeg")), ("files", ("b.jpg", jpg, "image/jpeg"))],
        data={"kinds": ["menu", "bogus"]},
    )
    assert r.status_code == 201, r.text
    a, b = r.json()["saved"]
    assert orch.store.load(pid).input.media_kinds == {a: "menu"}  # 모르는 값은 버린다


# ── B. 흐린 배경 맞춤 ────────────────────────────────────


def test_square_photos_are_shown_whole_over_a_blur():
    assert _fit(1080, 1920, 1.0).startswith("split[b0][f0]")
    assert "force_original_aspect_ratio=decrease" in _fit(1080, 1920, 1.33)
    assert "split" not in _fit(1080, 1920, 0.75)  # 3:4 세로 사진은 예전처럼 채운다
    assert "split" not in _fit(1080, 1920, None)


# ── D. AI 그림 점검·소스 통일 ────────────────────────────


def asset(sid, path, source="generated", provider="cloudflare:klein"):
    return Asset(
        scene_id=sid,
        image=ImageAsset(prompt="p", path=path, source=source, provider=provider),
        voice=VoiceAsset(text="t", voice="v"),
    )


async def test_generated_pictures_are_flagged_not_replaced(tmp_path):
    for name in ("s1.png", "s2.png", "me.jpg"):
        (tmp_path / name).write_bytes(b"x")
    assets = [asset("S1", "s1.png"), asset("S2", "s2.png"), asset("S3", "me.jpg", "user")]
    llm = FakeLLM()
    notes = await check_images(llm, assets, tmp_path)
    assert notes == ["S2 그림: 글자가 보여요 — '다른 그림'으로 바꿀 수 있어요"]
    assert assets[1].image.check.issues == ["text"] and assets[1].image.path == "s2.png"
    assert all("me.jpg" not in i for i in llm.images)  # 올린 사진은 보내지 않는다
    # 이미 본 그림은 다시 보내지 않는다
    llm.calls.clear()
    assert await check_images(llm, assets, tmp_path) == []
    assert "s5_image_check" not in llm.calls


def test_gemini_reads_local_files(tmp_path):
    from app.adapters.llm.gemini import _image_part

    f = tmp_path / "a.webp"
    f.write_bytes(b"RIFF....WEBP")
    part = _image_part(str(f))
    assert part.inline_data.mime_type == "image/webp" and part.inline_data.data == f.read_bytes()
    assert _image_part("https://i.ytimg.com/x.jpg").file_data.file_uri.startswith("https://")


async def test_mixed_sources_are_redrawn_to_match(orch, tmp_path):
    from app.steps.s5_prompts import unify_sources

    class Spent(ImageAdapter):
        wants_english_prompts = True

        async def generate(self, req):
            raise ImageQuotaExceeded("한도")

    class Space(ImageAdapter):
        wants_english_prompts = True

        async def generate(self, req):
            req.out_path.with_suffix(".webp").write_bytes(b"x")
            return ImageResult(req.out_path.with_suffix(".webp"), "generated", "hfspace:schnell")

    chain = ImageChain([("cloudflare", Spent()), ("hfspace", Space())])
    chain._exhausted.add("cloudflare")  # 앞 장면을 그린 뒤 한도가 바닥났다
    made = [asset("S1", "a.png"), asset("S2", "b.webp", provider="hfspace:schnell")]

    class Ctx:
        project_dir = tmp_path
        warnings: list[str] = []

        def warn(self, msg):
            self.warnings.append(msg)

    ctx = Ctx()
    await unify_sources(chain, made, tmp_path, ctx)
    assert {a.image.provider for a in made} == {"hfspace:schnell"}
    assert "S1" in ctx.warnings[0]
    assert Path(tmp_path / made[0].image.path).exists()


async def test_redraw_keeps_the_picture_when_only_stock_photos_are_left(tmp_path):
    from app.steps.s5_prompts import unify_sources

    class Down(ImageAdapter):
        wants_english_prompts = True

        async def generate(self, req):
            raise RuntimeError("Space 멈춤")

    class Stock(ImageAdapter):
        async def generate(self, req):
            out = req.out_path.with_suffix(".jpg")
            out.write_bytes(b"x")
            return ImageResult(out, "stock", "pixabay")

    chain = ImageChain([("cloudflare", Down()), ("hfspace", Down()), ("stock", Stock())])
    chain._exhausted.add("cloudflare")
    made = [asset("S1", "a.png"), asset("S2", "b.webp", provider="hfspace:schnell")]

    class Ctx:
        project_dir = tmp_path
        warnings: list[str] = []

        def warn(self, msg):
            self.warnings.append(msg)

    ctx = Ctx()
    await unify_sources(chain, made, tmp_path, ctx)
    assert made[0].image.path == "a.png" and made[0].image.source == "generated"
    assert ctx.warnings == []
    assert not list(tmp_path.glob("*.jpg"))  # 쓰지 않은 무료 사진은 지운다


async def test_photos_with_kinds_only_redo_from_the_script(orch, sample_input):
    p = orch.create_project(sample_input)
    await orch.run_all(p.id)
    inp = orch.store.load(p.id).input
    changed = inp.model_copy(
        update={"user_media": ["media/a.jpg"], "media_kinds": {"media/a.jpg": "menu"}}
    )
    p = await orch.edit(p.id, "input", changed)
    # 사진(S5)과 종류(S4)가 함께 바뀌면 S4부터 (검색·분석은 다시 하지 않는다)
    assert [p.status[s] for s in ("s2", "s3", "s4", "s5")] == ["done", "done", "stale", "stale"]


async def test_rejected_photo_leaves_no_orphans(client, orch):
    """여러 장 중 하나가 거절되면 앞에서 저장한 파일도 남기지 않는다."""
    pid = (await client.post("/projects", json={"topic": "홈트"})).json()["id"]
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    r = await client.post(
        f"/projects/{pid}/media",
        files=[
            ("files", ("ok.jpg", jpg, "image/jpeg")),
            ("files", ("bad.jpg", b"not", "image/jpeg")),
        ],
    )
    assert r.status_code == 415 and "사진 파일이 아니에요" in r.json()["detail"]
    media = orch.store.project_dir(pid) / "media"
    assert not media.exists() or not list(media.glob("*"))


async def test_ai_calls_outside_steps_are_recorded(tmp_path):
    """가게 입력 확인처럼 단계 밖에서 부른 AI도 사용 기록에 남는다 (전에는 0건)."""
    from app.adapters.fake import fake_adapters
    from app.config import Settings
    from app.metrics import Metrics, record_llm_call
    from app.orchestrator import Orchestrator
    from app.store import ProjectStore

    m = Metrics(tmp_path / "metrics.jsonl")
    store = ProjectStore(tmp_path / "data")
    Orchestrator(store, fake_adapters(), Settings(_env_file=None), metrics=m)
    record_llm_call(task="shop_check", model="lite", sec=1.0, ok=True)
    rows = [r for r in m.read() if r.get("event") == "llm_call"]
    assert rows and rows[0]["task"] == "shop_check" and rows[0]["step"] == ""
