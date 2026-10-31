"""공개 Space로 영상 만들기 (D20). 가짜 Gradio 서버로만 본다 (실제 호출 없음)."""

import asyncio
import json

import httpx
import pytest

from app.adapters.base import VideoGenRequest
from app.adapters.fake import FakeVideoGen
from app.adapters.registry import build_adapters
from app.adapters.video_gen.errors import VideoGenError
from app.adapters.video_gen.space import BASE, SMALL, SpaceVideoGen, attempts
from app.config import Settings
from app.main import create_app
from app.media import MediaError

CLIP = f"{BASE}/file=/tmp/gradio/abc/out.mp4"
OK = "event: complete\ndata: " + json.dumps([{"video": {"url": CLIP}}, 7]) + "\n\n"


class Server:
    """Gradio를 흉내 낸다. streams는 시도마다 돌려줄 SSE 본문(없으면 끊김)."""

    def __init__(self, *streams):
        self.streams = list(streams or [OK])
        self.calls: list[dict] = []
        self.seen: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.seen.append(req)
        url = str(req.url)
        if url.endswith("/upload"):
            return httpx.Response(200, json=["/tmp/gradio/up/scene.png"])
        if req.method == "POST":
            self.calls.append(json.loads(req.content))
            return httpx.Response(200, json={"event_id": "e1"})
        if url == CLIP:
            return httpx.Response(200, content=b"mp4-bytes")
        body = self.streams.pop(0)
        if body is None:
            raise httpx.RemoteProtocolError("끊김", request=req)
        return httpx.Response(200, text=body)


async def _copy(src, out):
    out.write_bytes(src.read_bytes())
    return out


async def _clean(src, out):
    out.write_bytes(b"clean-jpeg")
    return out


def adapter(server, token="hf_faketoken"):
    return SpaceVideoGen(
        token, transport=httpx.MockTransport(server), conform_fn=_copy, shrink_fn=_clean
    )


def request(tmp_path, seconds=3.0):
    image = tmp_path / "김철수_집앞.png"
    image.write_bytes(b"\x89PNG-small-with-exif")
    return VideoGenRequest(image, "a woman stretching", 7, seconds, tmp_path / "out" / "c.mp4")


def test_size_follows_what_the_space_could_actually_do():
    assert (attempts(3)[0].height, attempts(3)[0].width) == (1280, 720)
    assert (attempts(6)[0].height, attempts(6)[0].width) == SMALL  # 720×1280 7초는 4회 모두 실패
    assert attempts(100)[0].seconds == 7
    assert attempts(0.1)[0].seconds == 1.5


async def test_makes_a_clip_without_any_cost(tmp_path):
    server = Server()
    result = await adapter(server).generate(request(tmp_path))
    assert result.path.read_bytes() == b"mp4-bytes"
    assert result.usd == 0
    assert result.provider == "hf-space:Lightricks/ltx-video-distilled"
    assert not list(result.path.parent.glob("*.raw.mp4"))
    data = server.calls[0]["data"]
    assert data[2]["path"] == "/tmp/gradio/up/scene.png"
    assert data[4:8] == [1280, 720, "image-to-video", 3.0]
    assert data[9] == 7 and data[10] is False  # 정한 seed를 쓴다


async def test_only_a_cleaned_copy_with_a_fixed_name_leaves(tmp_path):
    server = Server()
    await adapter(server).generate(request(tmp_path))
    upload = next(r for r in server.seen if str(r.url).endswith("/upload"))
    body = upload.read()
    assert b"clean-jpeg" in body
    assert b'filename="scene.jpg"' in body
    assert "김철수".encode() not in body and b"with-exif" not in body
    assert not list(tmp_path.rglob("*.send.jpg"))


async def test_upload_happens_once_even_when_retrying(tmp_path):
    server = Server("event: error\ndata: null\n\n", OK)
    await adapter(server).generate(request(tmp_path))
    assert sum(str(r.url).endswith("/upload") for r in server.seen) == 1


async def test_token_goes_to_the_space_but_not_to_the_file_download(tmp_path):
    server = Server()
    await adapter(server).generate(request(tmp_path))
    post = next(r for r in server.seen if r.method == "POST")
    assert post.headers["authorization"] == "Bearer hf_faketoken"
    download = next(r for r in server.seen if str(r.url) == CLIP)
    assert "authorization" not in download.headers


async def test_works_without_a_token(tmp_path):
    server = Server()
    await adapter(server, token="").generate(request(tmp_path))
    assert "authorization" not in server.seen[0].headers


@pytest.mark.parametrize("first", ["event: error\ndata: null\n\n", None, "event: heartbeat\n\n"])
async def test_failed_try_retries_at_the_smaller_size(tmp_path, first):
    server = Server(first, OK)
    result = await adapter(server).generate(request(tmp_path))
    assert result.path.exists()
    assert [c["data"][4] for c in server.calls] == [1280, 1024]


async def test_gives_up_with_a_next_step(tmp_path):
    bad = "event: error\ndata: null\n\n"
    with pytest.raises(VideoGenError, match="유료 방식"):
        await adapter(Server(bad, bad)).generate(request(tmp_path))


async def test_same_size_is_not_tried_again_after_an_error(tmp_path):
    server = Server("event: error\ndata: null\n\n", OK)
    with pytest.raises(VideoGenError, match="유료 방식"):
        await adapter(server).generate(request(tmp_path, seconds=6))
    assert len(server.calls) == 1


async def test_cut_stream_at_small_size_is_tried_again(tmp_path):
    server = Server(None, OK)
    assert (await adapter(server).generate(request(tmp_path, seconds=6))).path.exists()
    assert [c["data"][4] for c in server.calls] == [1024, 1024]


async def test_finished_result_is_kept_when_the_stream_never_closes(tmp_path):
    # 결과 뒤에 스트림이 이어져도 기다리지 않는다
    server = Server(OK + "event: heartbeat\ndata: null\n\n")
    assert (await adapter(server).generate(request(tmp_path))).path.exists()
    assert len(server.calls) == 1


async def test_overall_time_limit_frees_the_project(tmp_path, monkeypatch):
    monkeypatch.setattr("app.adapters.video_gen.space.RESULT_TIMEOUT", 0.05)

    class Endless(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.01)
                yield b"event: heartbeat\ndata: null\n\n"

    def handler(req):
        if str(req.url).endswith("/upload"):
            return httpx.Response(200, json=["/tmp/x"])
        if req.method == "POST":
            return httpx.Response(200, json={"event_id": "e"})
        return httpx.Response(200, stream=Endless())

    g = SpaceVideoGen(
        "", transport=httpx.MockTransport(handler), conform_fn=_copy, shrink_fn=_clean
    )
    with pytest.raises(VideoGenError, match="오래"):
        await g.generate(request(tmp_path))


async def test_download_is_retried_because_the_clip_used_quota(tmp_path):
    class Once(Server):
        tries = 0

        def __call__(self, req):
            if str(req.url) == CLIP and Once.tries == 0:
                Once.tries = 1
                return httpx.Response(503)
            return super().__call__(req)

    server = Once()
    assert (await adapter(server).generate(request(tmp_path))).path.exists()
    assert len(server.calls) == 1


async def test_clip_that_cannot_be_downloaded_is_a_plain_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("app.adapters.video_gen.space.DOWNLOAD_WAIT", 0)

    class Gone(Server):
        def __call__(self, req):
            if str(req.url) == CLIP:
                self.seen.append(req)
                return httpx.Response(503)
            return super().__call__(req)

    server = Gone()
    with pytest.raises(VideoGenError, match="받지 못했어요"):
        await adapter(server).generate(request(tmp_path))
    assert sum(str(r.url) == CLIP for r in server.seen) == 3


async def test_broken_picture_says_so(tmp_path):
    async def broken(src, out):
        raise MediaError("Invalid data found")

    g = SpaceVideoGen(
        "", transport=httpx.MockTransport(Server()), conform_fn=_copy, shrink_fn=broken
    )
    with pytest.raises(VideoGenError, match="다른 그림"):
        await g.generate(request(tmp_path))


async def test_offline_is_told_as_offline(tmp_path):
    def handler(req):
        raise httpx.ConnectError("없음", request=req)

    g = SpaceVideoGen(
        "", transport=httpx.MockTransport(handler), conform_fn=_copy, shrink_fn=_clean
    )
    with pytest.raises(VideoGenError, match="인터넷"):
        await g.generate(request(tmp_path))


async def test_odd_call_response_is_a_plain_failure(tmp_path):
    def handler(req):
        if str(req.url).endswith("/upload"):
            return httpx.Response(200, json=["/tmp/x"])
        return httpx.Response(200, json=["not", "an", "object"])

    g = SpaceVideoGen(
        "", transport=httpx.MockTransport(handler), conform_fn=_copy, shrink_fn=_clean
    )
    with pytest.raises(VideoGenError):
        await g.generate(request(tmp_path))


async def test_quota_is_explained_and_not_retried(tmp_path):
    server = Server('event: error\ndata: "You have exceeded your GPU quota"\n\n')
    with pytest.raises(VideoGenError, match="사용량"):
        await adapter(server).generate(request(tmp_path))
    assert len(server.calls) == 1


async def test_stopped_queue_is_a_plain_message(tmp_path):
    def handler(req):
        if str(req.url).endswith("/upload"):
            return httpx.Response(200, json=["/tmp/x"])
        return httpx.Response(503, json={"detail": "Queue is stopped."})

    g = SpaceVideoGen(
        "", transport=httpx.MockTransport(handler), conform_fn=_copy, shrink_fn=_clean
    )
    with pytest.raises(VideoGenError, match="멈춘"):
        await g.generate(request(tmp_path))


async def test_never_downloads_from_another_host(tmp_path):
    evil = 'event: complete\ndata: [{"video": {"url": "https://evil.example/x.mp4"}}]\n\n'
    server = Server(evil)
    with pytest.raises(VideoGenError):
        await adapter(server).generate(request(tmp_path))
    assert not any("evil" in str(r.url) for r in server.seen)


def test_space_mode_builds_without_a_token():
    on = Settings(_env_file=None, video_gen="space", hf_token="")
    assert isinstance(build_adapters(on, problems=[]).video_gen, SpaceVideoGen)


async def test_settings_need_consent_but_no_token(orch, store, tmp_path):
    settings = Settings(_env_file=None, data_dir=store.data_dir)
    app = create_app(settings, orch, env_path=tmp_path / ".env")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        free = {"on": True, "mode": "space"}
        r = await c.post("/settings/video-gen", json=free)
        assert r.status_code == 422  # 그림이 외부로 간다는 동의 없음
        r = await c.post("/settings/video-gen", json={"on": True, "accept_cost": True})
        assert r.status_code == 422  # 어느 방식에 동의했는지 모른다 (예전 화면)
        r = await c.post("/settings/video-gen", json={**free, "accept_cost": True})
        assert r.status_code == 200
        assert r.json()["video_gen"]["mode"] == "space"
        assert r.json()["video_gen"]["free"] is True
        assert "VIDEO_GEN=space" in (tmp_path / ".env").read_text(encoding="utf-8")


async def test_config_tells_the_screen_it_is_free(orch, store):
    orch.adapters.video_gen = FakeVideoGen()
    settings = Settings(_env_file=None, data_dir=store.data_dir, video_gen="space")
    app = create_app(settings, orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/config")).json()["video_gen"]["free"] is True
