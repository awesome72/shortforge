"""무료 이미지 소스 (D12): Cloudflare Workers AI 생성, Pexels 사진, 체인 대체. 가짜 서버만 쓴다."""

import base64
import json

import httpx
import pytest

from app.adapters.base import ImageAdapter, ImageQuotaExceeded, ImageRequest, ImageResult
from app.adapters.image.chain import ImageChain
from app.adapters.image.cloudflare import (
    KLEIN_4B,
    SCHNELL,
    CloudflareImageAdapter,
    CloudflareImageError,
    NeuronMeter,
    estimate_neurons,
)
from app.adapters.image.pexels import PexelsAdapter
from app.adapters.registry import build_image
from app.config import Settings

JPEG = b"\xff\xd8\xff\xe0cloudflare-jpeg"


def req(tmp_path, seed=7, query="yoga mat"):
    return ImageRequest("hands on a yoga mat", "blurry", seed, tmp_path / "S1", query=query)


# ── Cloudflare ────────────────────────────────────────────


class FakeCF:
    def __init__(self, status=200, body=None):
        self.status, self.body = status, body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = self.body or {"result": {"image": base64.b64encode(JPEG).decode()}, "success": True}
        return httpx.Response(self.status, json=body)


def cf(tmp_path, server, model=KLEIN_4B, limit=10_000):
    meter = NeuronMeter(tmp_path / "db.sqlite", limit)
    return CloudflareImageAdapter(
        "acct123", "tok", meter, model=model, transport=httpx.MockTransport(server)
    ), meter


def test_neuron_estimates_match_price_table():
    assert estimate_neurons(KLEIN_4B, 720, 1280) == pytest.approx(6 * 26.05)  # 2×3 타일
    assert estimate_neurons(SCHNELL, 0, 0) == pytest.approx(4 * 4.8 + 4 * 9.6)


async def test_klein_sends_multipart_with_size_and_seed(tmp_path):
    server = FakeCF()
    adapter, meter = cf(tmp_path, server)
    res = await adapter.generate(req(tmp_path, seed=4242))
    r = server.requests[0]
    assert r.url.path == f"/client/v4/accounts/acct123/ai/run/{KLEIN_4B}"
    assert r.headers["authorization"] == "Bearer tok"
    assert r.headers["content-type"].startswith("multipart/form-data")
    body = r.content.decode("utf-8", "replace")
    for name, value in [("prompt", "hands on a yoga mat"), ("width", "720"), ("height", "1280"),
                        ("seed", "4242")]:  # fmt: skip
        assert f'name="{name}"\r\n\r\n{value}\r\n' in body
    assert res.path.suffix == ".jpg" and res.path.read_bytes() == JPEG
    assert res.source == "generated" and res.provider == "cloudflare:flux-2-klein-4b"
    assert meter.used() == pytest.approx(156.3)


async def test_schnell_sends_json_without_seed(tmp_path):
    server = FakeCF()
    adapter, _ = cf(tmp_path, server, model=SCHNELL)
    await adapter.generate(req(tmp_path))
    assert json.loads(server.requests[0].content) == {"prompt": "hands on a yoga mat", "steps": 4}


async def test_local_meter_blocks_before_calling(tmp_path):
    server = FakeCF()
    adapter, _ = cf(tmp_path, server, limit=100)  # 1장(156)도 못 만든다
    with pytest.raises(ImageQuotaExceeded, match="00:00 UTC"):
        await adapter.generate(req(tmp_path))
    assert server.requests == []


@pytest.mark.parametrize(
    ("status", "errors", "exc"),
    [
        (429, [{"code": 3036, "message": "rate limited"}], ImageQuotaExceeded),
        (400, [{"code": 4006, "message": "you have used up your daily free allocation"}],
         ImageQuotaExceeded),
        (400, [{"code": 5006, "message": "bad input"}], CloudflareImageError),
    ],
)  # fmt: skip
async def test_api_errors(tmp_path, status, errors, exc):
    adapter, meter = cf(tmp_path, FakeCF(status, {"success": False, "errors": errors}))
    with pytest.raises(exc):
        await adapter.generate(req(tmp_path))
    assert meter.used() == 0  # 실패한 호출은 기록하지 않는다


def test_missing_credentials():
    with pytest.raises(CloudflareImageError, match="CLOUDFLARE_ACCOUNT_ID"):
        CloudflareImageAdapter("", "", meter=None)


# ── Pexels ────────────────────────────────────────────────


class FakePexels:
    def __init__(self, n=3, status=200):
        self.n, self.status = n, status
        self.searches: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.pexels.com":
            self.searches.append(request)
            if self.status != 200:
                return httpx.Response(self.status)
            photos = [
                {"id": 100 + i, "photographer": f"작가{i}", "url": f"https://www.pexels.com/photo/{i}/",
                 "src": {"portrait": f"https://images.pexels.com/p/{100 + i}.jpeg?fit=crop"}}
                for i in range(self.n)
            ]  # fmt: skip
            return httpx.Response(200, json={"photos": photos})
        return httpx.Response(200, content=JPEG)


async def test_pexels_portrait_search_credit_and_no_repeats(tmp_path):
    server = FakePexels(n=3)
    px = PexelsAdapter("key", transport=httpx.MockTransport(server))
    a = await px.generate(req(tmp_path, seed=0, query="yoga mat living room"))
    b = await px.generate(req(tmp_path, seed=0))
    q = server.searches[0].url.params
    assert q["query"] == "yoga mat living room" and q["orientation"] == "portrait"
    assert server.searches[0].headers["authorization"] == "key"
    assert a.source == "stock" and a.provider == "pexels" and a.path.suffix == ".jpeg"
    assert a.credit.startswith("Photo by 작가0 on Pexels")
    assert b.credit.startswith("Photo by 작가1")  # 같은 seed여도 이미 쓴 사진은 피한다


async def test_pexels_no_results_and_rate_limit(tmp_path):
    empty = PexelsAdapter("key", transport=httpx.MockTransport(FakePexels(n=0)))
    assert await empty.generate(req(tmp_path)) is None
    limited = PexelsAdapter("key", transport=httpx.MockTransport(FakePexels(status=429)))
    with pytest.raises(ImageQuotaExceeded):
        await limited.generate(req(tmp_path))


# ── Pixabay ───────────────────────────────────────────────


class FakePixabay:
    def __init__(self, n=3, status=200, body=None):
        self.n, self.status, self.body = n, status, body
        self.searches: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/":  # 이미지 주소도 pixabay.com이라 경로로 구분한다
            self.searches.append(request)
            if self.status != 200:
                return httpx.Response(self.status, text=self.body or "")
            hits = [
                {"id": 500 + i, "user": f"user{i}",
                 "pageURL": f"https://pixabay.com/photos/x-{500 + i}/",
                 "largeImageURL": f"https://pixabay.com/get/{500 + i}_1280.jpg",
                 "webformatURL": f"https://pixabay.com/get/{500 + i}_640.jpg"}
                for i in range(self.n)
            ]  # fmt: skip
            return httpx.Response(200, json={"total": self.n, "hits": hits})
        assert request.url.path.endswith("_1280.jpg")  # largeImageURL을 내려받는다
        return httpx.Response(200, content=JPEG)


def pixabay(tmp_path, server):
    from app.adapters.image.pixabay import PixabayAdapter
    from app.cache import Cache

    return PixabayAdapter(
        "pkey", Cache(tmp_path / "db.sqlite"), transport=httpx.MockTransport(server)
    )


async def test_pixabay_vertical_search_download_credit(tmp_path):
    server = FakePixabay()
    px = pixabay(tmp_path, server)
    res = await px.generate(req(tmp_path, seed=1, query="yoga mat living room"))
    q = server.searches[0].url.params
    assert q["key"] == "pkey" and q["q"] == "yoga mat living room"
    assert (
        q["orientation"] == "vertical" and q["image_type"] == "photo" and q["safesearch"] == "true"
    )
    assert res.source == "stock" and res.provider == "pixabay"
    assert (
        res.path.suffix == ".jpg" and res.path.read_bytes() == JPEG
    )  # 내려받아 쓴다 (hotlink 금지)
    assert res.credit == "Image by user1 from Pixabay · https://pixabay.com/photos/x-501/"


async def test_pixabay_caches_search_24h_and_avoids_repeats(tmp_path):
    server = FakePixabay(n=2)
    px = pixabay(tmp_path, server)
    a = await px.generate(req(tmp_path, seed=0))
    b = await px.generate(req(tmp_path, seed=0))
    assert len(server.searches) == 1  # 약관: 같은 검색은 24시간 캐시
    assert a.credit != b.credit  # 이미 쓴 사진은 피한다
    fresh = pixabay(tmp_path, server)  # 새 인스턴스도 같은 캐시(DB)를 본다
    await fresh.generate(req(tmp_path))
    assert len(server.searches) == 1


async def test_pixabay_errors(tmp_path):
    from app.adapters.image.pixabay import PixabayError

    assert await pixabay(tmp_path, FakePixabay(n=0)).generate(req(tmp_path, query="none")) is None
    with pytest.raises(ImageQuotaExceeded, match="60초"):
        await pixabay(tmp_path, FakePixabay(status=429)).generate(req(tmp_path, query="q429"))
    bad = FakePixabay(status=400, body="[ERROR 400] Invalid or missing API key")
    with pytest.raises(PixabayError, match="Invalid or missing API key"):
        await pixabay(tmp_path, bad).generate(req(tmp_path, query="q400"))
    with pytest.raises(PixabayError, match="PIXABAY_API_KEY"):
        from app.adapters.image.pixabay import PixabayAdapter

        PixabayAdapter("", cache=None)


# ── 체인 ──────────────────────────────────────────────────


class Stub(ImageAdapter):
    wants_english_prompts = True  # 실제 생성·검색 어댑터와 같게

    def __init__(self, behavior, source="generated"):
        self.behavior, self.source, self.calls = behavior, source, 0

    async def generate(self, r):
        self.calls += 1
        if isinstance(self.behavior, Exception):
            raise self.behavior
        if self.behavior is None:
            return None
        return ImageResult(path=r.out_path, source=self.source, provider=self.behavior)


async def test_chain_falls_through_and_explains(tmp_path):
    quota = Stub(ImageQuotaExceeded("한도 끝"))
    broken = Stub(RuntimeError("boom"))
    stock = Stub("pexels", source="stock")
    chain = ImageChain([("cloudflare", quota), ("comfyui", broken), ("stock", stock)])
    assert (await chain.generate(req(tmp_path))).provider == "pexels"
    assert (await chain.generate(req(tmp_path))).provider == "pexels"
    assert quota.calls == 1  # 한도가 바닥난 소스는 같은 실행에서 다시 부르지 않는다
    assert broken.calls == 2
    notes = chain.drain_notices()
    assert any("cloudflare: 한도 끝" in n for n in notes)
    assert any("comfyui 실패(RuntimeError: boom)" in n for n in notes)
    assert len(notes) == 2  # 같은 알림은 한 번만


async def test_chain_all_fail_returns_none(tmp_path):
    chain = ImageChain([("stock", Stub(None))])
    assert await chain.generate(req(tmp_path)) is None


def test_image_mode_parsing_and_registry():
    s = Settings(
        _env_file=None, image_mode=" cloudflare , stock ", cloudflare_account_id="a",
        cloudflare_api_token="t", pixabay_api_key="k",
    )  # fmt: skip
    assert s.image_mode == "cloudflare,stock" and s.image_sources == ["cloudflare", "stock"]
    chain = build_image(s)
    assert [name for name, _ in chain.sources] == ["cloudflare", "stock"]
    assert type(chain.sources[1][1]).__name__ == "PixabayAdapter"  # stock = Pixabay (D12)
    assert chain.wants_english_prompts
    pexels = build_image(Settings(_env_file=None, image_mode="pexels", pexels_api_key="k"))
    assert type(pexels.sources[0][1]).__name__ == "PexelsAdapter"
    assert Settings(_env_file=None, image_mode="upload").image_sources == []
    with pytest.raises(ValueError, match="dalle"):
        Settings(_env_file=None, image_mode="cloudflare,dalle")


# ── S5 통합 ───────────────────────────────────────────────


async def test_s5_uses_english_prompts_and_records_source(orch, store, adapters, sample_input):
    stock = Stub("pexels", source="stock")
    adapters.image = ImageChain(
        [("cloudflare", Stub(ImageQuotaExceeded("한도 끝"))), ("stock", stock)]
    )
    sample_input.user_media = ["me.jpg"]  # S1은 본인 사진 → 생성·검색 안 함
    p = await orch.run_all(store.create(sample_input).id)

    a1, a2 = p.assets[0], p.assets[1]
    assert a1.image.source == "user" and a1.image.provider is None
    assert a2.image.source == "stock" and a2.image.provider == "pexels"
    assert a2.image.prompt.startswith("photo of scene S2, hands only, vertical 9:16")
    assert a2.image.query == "office S2"
    assert stock.calls == 4
    assert any("cloudflare: 한도 끝" in w for w in p.warnings["s5"])


async def test_s5_english_prompt_failure_falls_back_to_korean(orch, store, adapters, sample_input):
    def broken(user):
        raise RuntimeError("LLM down")

    adapters.llm._s5_image_prompts = broken
    p = await orch.run_all(store.create(sample_input).id)
    assert p.status["s5"].value == "done"
    assert p.assets[0].image.prompt.startswith("hook 장면")
    assert any("영문 이미지 프롬프트 변환에 실패" in w for w in p.warnings["s5"])


async def test_s5_skips_prompt_call_when_all_scenes_have_photos(
    orch, store, adapters, sample_input
):
    sample_input.user_media = [f"p{i}.jpg" for i in range(5)]
    await orch.run_all(store.create(sample_input).id)
    assert "s5_image_prompts" not in adapters.llm.calls
