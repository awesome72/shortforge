"""Cloudflare가 막히면 Hugging Face 공개 Space로 그린다 (D22). 외부 호출은 가짜 서버."""

import httpx
import pytest

from app.adapters.base import ImageAdapter, ImageQuotaExceeded, ImageRequest
from app.adapters.image.chain import ImageChain
from app.adapters.image.hfspace import BASE, HFSpaceImageAdapter, HFSpaceImageError
from app.config import Settings

WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 16
FILE = f"{BASE}/file=/tmp/gradio/abc/image.webp"


def space(event="complete", url=FILE, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        url_ = str(request.url)
        if seen is not None:
            seen.append((request.method, url_, request.headers.get("authorization")))
        if request.method == "POST" and url_.endswith("/call/infer"):
            return httpx.Response(200, json={"event_id": "e1"})
        if url_.endswith("/call/infer/e1"):
            quota = '"You have exceeded your GPU quota"'
            data = f'[{{"url": "{url}"}}, 5]' if event == "complete" else quota
            return httpx.Response(200, text=f"event: {event}\ndata: {data}\n\n")
        if "/file=" in url_ or "evil" in url_:
            return httpx.Response(200, content=WEBP)
        raise AssertionError(url_)

    return httpx.MockTransport(handler)


def req(tmp_path):
    return ImageRequest(prompt="green onions", negative="", seed=5, out_path=tmp_path / "S1_x")


async def test_draws_without_sending_any_token(tmp_path):
    seen = []
    r = await HFSpaceImageAdapter(transport=space(seen=seen)).generate(req(tmp_path))
    assert r.path.suffix == ".webp" and r.path.read_bytes() == WEBP
    assert r.source == "generated" and r.provider == "hfspace:FLUX.1-schnell"
    assert all(a is None for _m, _u, a in seen)  # 영상용 HF_TOKEN을 그림 Space에 넘기지 않는다


async def test_quota_moves_the_chain_on(tmp_path):
    with pytest.raises(ImageQuotaExceeded):
        await HFSpaceImageAdapter(transport=space(event="error")).generate(req(tmp_path))


async def test_refuses_files_from_elsewhere(tmp_path):
    adapter = HFSpaceImageAdapter(transport=space(url="https://evil.example/x.webp"))
    with pytest.raises(HFSpaceImageError):
        await adapter.generate(req(tmp_path))


async def test_chain_falls_back_from_cloudflare_to_the_space(tmp_path):
    class SpentCloudflare(ImageAdapter):
        wants_english_prompts = True

        async def generate(self, req):
            raise ImageQuotaExceeded("Cloudflare 이미지 무료 한도 초과")

    chain = ImageChain(
        [("cloudflare", SpentCloudflare()), ("hfspace", HFSpaceImageAdapter(transport=space()))]
    )
    r = await chain.generate(req(tmp_path))
    assert r.provider.startswith("hfspace")
    assert any("cloudflare" in n for n in chain.drain_notices())


def test_space_sits_right_after_cloudflare(monkeypatch):
    monkeypatch.setenv("HF_IMAGE_FALLBACK", "true")
    cf = {"cloudflare_account_id": "a", "cloudflare_api_token": "t"}
    assert Settings(_env_file=None).image_sources == ["hfspace"]  # 키가 없어도 그린다
    assert Settings(_env_file=None, pixabay_api_key="p", **cf).image_sources == [
        "cloudflare",
        "hfspace",
        "stock",
    ]
    # .env에 적어 둔 방식에도 Cloudflare 바로 뒤에 넣는다
    s = Settings(_env_file=None, image_mode="video,cloudflare,stock")
    assert s.image_sources == ["video", "cloudflare", "hfspace", "stock"]
    assert Settings(_env_file=None, image_mode="stock").image_sources == ["stock"]
    assert Settings(_env_file=None, image_mode="upload").image_sources == []
    off = Settings(_env_file=None, image_mode="cloudflare,stock", hf_image_fallback=False)
    assert off.image_sources == ["cloudflare", "stock"]


def test_registry_builds_the_space_source(monkeypatch):
    from app.adapters.registry import build_image

    monkeypatch.setenv("HF_IMAGE_FALLBACK", "true")
    chain = build_image(Settings(_env_file=None), problems=[])
    assert [name for name, _ in chain.sources] == ["hfspace"]
    assert chain.wants_english_prompts
