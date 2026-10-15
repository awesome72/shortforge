"""원격 ComfyUI 어댑터 (Step 8). 개발 PC에 GPU가 없으므로 가짜 ComfyUI 서버로 검증한다."""

import json

import httpx
import pytest

from app.adapters.base import ImageRequest
from app.adapters.image.comfyui import DEFAULT_WORKFLOW, ComfyUIAdapter, ComfyUIError, fill_workflow
from app.adapters.registry import build_image
from app.config import Settings

PNG = b"\x89PNG\r\n\x1a\nfake"


class FakeComfy:
    def __init__(self, pending_polls=2, fail=None):
        self.pending = pending_polls
        self.fail = fail
        self.submitted = None
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if path == "/prompt":
            self.submitted = json.loads(request.content)
            return httpx.Response(200, json={"prompt_id": "p1", "number": 0})
        if path == "/history/p1":
            if self.pending > 0:
                self.pending -= 1
                return httpx.Response(200, json={})  # 아직 큐에 있음
            if self.fail == "error":
                return httpx.Response(
                    200, json={"p1": {"status": {"status_str": "error"}, "outputs": {}}}
                )
            if self.fail == "no_output":
                return httpx.Response(
                    200, json={"p1": {"status": {"completed": True}, "outputs": {}}}
                )
            img = {"filename": "shortforge_00001_.png", "subfolder": "", "type": "output"}
            return httpx.Response(
                200,
                json={"p1": {"status": {"completed": True}, "outputs": {"9": {"images": [img]}}}},
            )
        if path == "/view":
            assert request.url.params["filename"] == "shortforge_00001_.png"
            return httpx.Response(200, content=PNG)
        return httpx.Response(404)


def adapter(server, **kw):
    return ComfyUIAdapter(
        "http://gpu-box:8188", poll_sec=0, transport=httpx.MockTransport(server), **kw
    )


def test_fill_workflow_keeps_types():
    wf = {"a": {"inputs": {"seed": "{{seed}}", "text": "{{prompt}}, 9:16", "w": "{{width}}"}}}
    out = fill_workflow(wf, {"seed": 42, "prompt": "퇴근길", "width": 768})
    assert out == {"a": {"inputs": {"seed": 42, "text": "퇴근길, 9:16", "w": 768}}}
    assert wf["a"]["inputs"]["seed"] == "{{seed}}"  # 원본은 그대로


def test_default_workflow_has_all_placeholders():
    text = DEFAULT_WORKFLOW.read_text(encoding="utf-8")
    for key in ("prompt", "negative", "seed", "width", "height"):
        assert "{{" + key + "}}" in text


async def test_generate_submits_polls_and_saves(tmp_path):
    server = FakeComfy(pending_polls=2)
    res = await adapter(server).generate(
        ImageRequest("hook 장면, warm light", "blurry", 1234, tmp_path / "S1.png")
    )
    assert res.path.read_bytes() == PNG
    assert res.source == "generated" and res.provider == "comfyui"
    nodes = server.submitted["prompt"]
    assert nodes["6"]["inputs"]["text"] == "hook 장면, warm light"
    assert nodes["7"]["inputs"]["text"] == "blurry"
    assert nodes["3"]["inputs"]["seed"] == 1234
    assert nodes["5"]["inputs"]["height"] == 1344
    assert server.calls.count("/history/p1") == 3


@pytest.mark.parametrize(
    ("fail", "msg"), [("error", "실행 오류"), ("no_output", "출력 이미지가 없다")]
)
async def test_generation_errors_are_explained(tmp_path, fail, msg):
    with pytest.raises(ComfyUIError, match=msg):
        await adapter(FakeComfy(pending_polls=0, fail=fail)).generate(
            ImageRequest("p", "n", 1, tmp_path / "x.png")
        )


async def test_timeout(tmp_path):
    with pytest.raises(ComfyUIError, match="초 안에"):
        await adapter(FakeComfy(pending_polls=10**6), timeout_sec=0.05).generate(
            ImageRequest("p", "n", 1, tmp_path / "x.png")
        )


async def test_unreachable_server(tmp_path):
    def offline(request):
        raise httpx.ConnectError("refused")

    a = ComfyUIAdapter("http://gpu-box:8188", transport=httpx.MockTransport(offline))
    with pytest.raises(ComfyUIError, match="연결할 수 없다"):
        await a.generate(ImageRequest("p", "n", 1, tmp_path / "x.png"))


def test_image_mode_switch_by_setting_only():
    """Gate: IMAGE_MODE 설정만으로 전환된다."""
    upload = build_image(Settings(_env_file=None, image_mode="upload"))
    comfy = build_image(
        Settings(_env_file=None, image_mode="comfyui", comfyui_url="http://gpu-box:8188")
    )
    assert type(upload).__name__ == "UploadImageAdapter"
    assert type(comfy).__name__ == "ImageChain"  # 생성 소스는 항상 체인으로 감싼다 (D12)
    assert [type(a).__name__ for _, a in comfy.sources] == ["ComfyUIAdapter"]
    with pytest.raises(ComfyUIError, match="COMFYUI_URL"):
        build_image(Settings(_env_file=None, image_mode="comfyui", comfyui_url=""))


async def test_s5_uses_generated_images_and_skips_photo_cycling(
    orch, store, adapters, sample_input, tmp_path
):
    server = FakeComfy(pending_polls=0)
    adapters.image = adapter(server)
    sample_input.user_media = ["me.jpg"]  # 첫 장면만 본인 사진, 나머지는 생성
    p = await orch.run_all(store.create(sample_input).id)
    sources = [a.image.source for a in p.assets]
    assert sources == ["user"] + ["generated"] * 4
    assert all(a.image.path.startswith("assets/") for a in p.assets[1:])
    assert not any("같은 사진을 다시 썼다" in w for w in p.warnings.get("s5", []))
