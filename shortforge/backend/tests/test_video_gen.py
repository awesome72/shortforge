"""장면 그림 → 영상 (D19). Hugging Face 경로는 가짜 서버로만 본다 (실제 호출·비용 없음)."""

import asyncio
import json

import httpx
import pytest

from app.adapters.base import VideoGenRequest
from app.adapters.fake import FakeVideoGen
from app.adapters.registry import build_adapters
from app.adapters.video_gen.errors import VideoGenError
from app.adapters.video_gen.hf import (
    MAX_SECONDS,
    HFVideoGen,
    check_token,
    estimate_usd,
    frames_for,
)
from app.config import Settings
from app.main import create_app
from app.media import MediaError
from app.publish import publish_kit
from app.spend import VIDEO_MODEL, VIDEO_PROVIDER, BudgetExceeded, SpendMeter

BASE = f"https://router.huggingface.co/fal-ai/{VIDEO_MODEL.provider_id}"
CLIP = "https://v3.fal.media/files/out.mp4"
RESPONSE_URL = "https://queue.fal.run/fal-ai/ltx-2-19b/requests/abc"


class Server:
    """fal 큐를 흉내 낸다: 요청 → 진행 중 → 완료 → 결과 → 파일."""

    def __init__(self, submit=200, result=200, statuses=("IN_PROGRESS", "COMPLETED")):
        self.submit, self.result = submit, result
        self.statuses = list(statuses)
        self.body: dict = {}
        self.seen: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.seen.append(req)
        url = str(req.url)
        if req.method == "POST":
            self.body = json.loads(req.content)
            if self.submit != 200:
                return httpx.Response(self.submit, json={"error": "no"})
            return httpx.Response(
                200,
                json={"request_id": "abc", "status": "IN_QUEUE", "response_url": RESPONSE_URL},
            )
        if url == CLIP:
            return httpx.Response(200, content=b"mp4-bytes")
        if "/status" in url:
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return httpx.Response(200, json={"status": status})
        if self.result != 200:
            return httpx.Response(self.result, json={"detail": "content rejected"})
        return httpx.Response(200, json={"video": {"url": CLIP}, "seed": 1})


async def _no_sleep(_):
    return None


async def _copy(src, out):
    out.write_bytes(src.read_bytes())
    return out


def adapter(server, tmp_path, budget=1.0, **kw):
    spend = SpendMeter(tmp_path / "s.db", budget, VIDEO_PROVIDER)
    return HFVideoGen(
        "hf_faketoken",
        spend,
        transport=httpx.MockTransport(server),
        sleep=_no_sleep,
        conform_fn=_copy,
        **kw,
    )


def request(tmp_path, seconds=4.0):
    image = tmp_path / "scene.png"
    image.write_bytes(b"\x89PNG-small")
    return VideoGenRequest(image, "a woman stretching", 7, seconds, tmp_path / "out" / "c.mp4")


def test_frames_follow_model_rule_and_stop_at_limit():
    assert frames_for(4.0) == 105  # 8k+1, 위로 올림
    assert (frames_for(4.0) - 1) % 8 == 0
    assert frames_for(100) == frames_for(MAX_SECONDS)  # 긴 장면도 비용은 상한까지만
    assert frames_for(0.1) >= 33


def test_price_matches_published_rate():
    # 페이지 예시: 121프레임 1280×720 = $0.0896 → 메가픽셀당 $0.0008
    assert VIDEO_MODEL.usd_per_sec == pytest.approx(0.01757, abs=1e-4)
    assert 0.06 < estimate_usd(4.0) < 0.09


async def test_generates_a_clip_through_the_hf_router(tmp_path):
    server = Server()
    g = adapter(server, tmp_path)
    result = await g.generate(request(tmp_path))
    assert result.path.read_bytes() == b"mp4-bytes"
    assert not list(result.path.parent.glob("*.raw.mp4"))
    post = server.seen[0]
    assert str(post.url) == f"{BASE}?_subdomain=queue"
    assert post.headers["authorization"] == "Bearer hf_faketoken"
    assert server.body["video_size"] == {"width": 704, "height": 1248}  # 세로
    assert server.body["generate_audio"] is False
    assert server.body["image_url"].startswith("data:image/png;base64,")
    assert server.body["num_frames"] == 105
    status = next(r for r in server.seen if "/status" in str(r.url))
    assert str(status.url).startswith("https://router.huggingface.co/fal-ai/fal-ai/ltx-2-19b/")
    assert "_subdomain=queue" in str(status.url)
    assert g.spend.used() == pytest.approx(result.usd)


async def test_token_is_not_sent_to_the_file_host(tmp_path):
    server = Server()
    await adapter(server, tmp_path).generate(request(tmp_path))
    download = next(r for r in server.seen if str(r.url) == CLIP)
    assert "authorization" not in download.headers


async def test_budget_stops_before_any_request(tmp_path):
    server = Server()
    g = adapter(server, tmp_path, budget=0.05)
    with pytest.raises(BudgetExceeded):
        await g.generate(request(tmp_path))
    assert server.seen == []


async def test_second_clip_over_budget_is_refused(tmp_path):
    server = Server()
    g = adapter(server, tmp_path, budget=0.1)
    await g.generate(request(tmp_path))
    with pytest.raises(BudgetExceeded):
        await g.generate(request(tmp_path))


@pytest.mark.parametrize(
    ("status", "word"), [(402, "크레딧"), (401, "권한"), (403, "권한"), (429, "잠시")]
)
async def test_failures_explain_what_to_do_and_cost_nothing(tmp_path, status, word):
    g = adapter(Server(submit=status), tmp_path)
    with pytest.raises(VideoGenError, match=word) as e:
        await g.generate(request(tmp_path))
    assert "hf_faketoken" not in str(e.value)
    assert g.spend.used() == 0


async def test_rejected_result_costs_nothing(tmp_path):
    g = adapter(Server(result=422), tmp_path)
    with pytest.raises(VideoGenError, match="다른 그림") as e:
        await g.generate(request(tmp_path))
    assert "content rejected" not in str(e.value)  # 영어 오류를 화면에 그대로 내지 않는다
    assert g.spend.used() == pytest.approx(0)


async def test_provider_failure_gives_the_money_back(tmp_path):
    g = adapter(Server(statuses=("FAILED",)), tmp_path)
    with pytest.raises(VideoGenError):
        await g.generate(request(tmp_path))
    assert g.spend.used() == pytest.approx(0)


class Flaky(Server):
    """접수 뒤 조회가 끊긴다: 공급자 쪽 작업은 계속 돌고 있다."""

    def __init__(self, failures, **kw):
        super().__init__(**kw)
        self.failures = list(failures)

    def __call__(self, req):
        if req.method == "GET" and self.failures and str(req.url) != CLIP:
            fail = self.failures.pop(0)
            if isinstance(fail, int):
                self.seen.append(req)
                return httpx.Response(fail, json={})
            raise httpx.ConnectError("끊김", request=req)
        return super().__call__(req)


@pytest.mark.parametrize("fail", [429, 503, "drop"])
async def test_lookups_that_break_are_retried(tmp_path, fail):
    g = adapter(Flaky([fail, fail, fail, fail]), tmp_path)
    result = await g.generate(request(tmp_path))
    assert result.path.exists()
    assert g.spend.used() == pytest.approx(result.usd)  # 한 번만 센다


@pytest.mark.parametrize("fail", [404, 503])
async def test_money_stays_counted_when_we_lose_track(tmp_path, fail):
    server = Flaky([fail] * 3, statuses=("IN_PROGRESS",))
    g = adapter(server, tmp_path, timeout_sec=0.05 if fail == 503 else 100)
    with pytest.raises(VideoGenError):
        await g.generate(request(tmp_path))
    assert g.spend.used() > 0  # 접수된 일은 청구될 수 있다


async def test_request_timeout_counts_toward_budget(tmp_path):
    def handler(req):
        raise httpx.ReadTimeout("느림", request=req)

    spend = SpendMeter(tmp_path / "s.db", 1.0, VIDEO_PROVIDER)
    g = HFVideoGen(
        "hf_x",
        spend,
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
        conform_fn=_copy,
    )
    with pytest.raises(VideoGenError):
        await g.generate(request(tmp_path))
    assert spend.used() > 0


async def test_connection_cut_after_sending_counts_toward_budget(tmp_path):
    def handler(req):
        raise httpx.ReadError("끊김", request=req)

    spend = SpendMeter(tmp_path / "s.db", 1.0, VIDEO_PROVIDER)
    g = HFVideoGen(
        "hf_x",
        spend,
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
        conform_fn=_copy,
    )
    with pytest.raises(VideoGenError):
        await g.generate(request(tmp_path))
    assert spend.used() > 0


@pytest.mark.parametrize("status", [401, 403, 404, 410])
async def test_only_content_rejection_gives_the_money_back(tmp_path, status):
    g = adapter(Server(result=status), tmp_path)
    with pytest.raises(VideoGenError):
        await g.generate(request(tmp_path))
    assert g.spend.used() > 0


@pytest.mark.parametrize(
    ("status", "word"), [(422, "다른 그림"), (503, "불안정"), (500, "불안정"), (404, "지금은")]
)
async def test_messages_blame_the_right_thing(tmp_path, status, word):
    with pytest.raises(VideoGenError, match=word):
        await adapter(Server(submit=status), tmp_path).generate(request(tmp_path))


async def test_odd_result_shape_is_a_plain_failure(tmp_path):
    class Odd(Server):
        def __call__(self, req):
            r = super().__call__(req)
            if req.method == "GET" and "/status" not in str(req.url):
                return httpx.Response(200, json={"video": "x"})
            return r

    with pytest.raises(VideoGenError):
        await adapter(Odd(), tmp_path).generate(request(tmp_path))


async def test_missing_ffmpeg_stops_before_spending(tmp_path, monkeypatch):
    def no_ffmpeg(name):
        raise MediaError("없음")

    monkeypatch.setattr("app.adapters.video_gen.hf.find_exe", no_ffmpeg)
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={})

    spend = SpendMeter(tmp_path / "s.db", 1.0, VIDEO_PROVIDER)
    g = HFVideoGen("hf_x", spend, transport=httpx.MockTransport(handler), sleep=_no_sleep)
    with pytest.raises(MediaError):
        await g.generate(request(tmp_path))
    assert seen == []
    assert spend.used() == 0


async def test_refused_connection_costs_nothing(tmp_path):
    def handler(req):
        raise httpx.ConnectError("없음", request=req)

    spend = SpendMeter(tmp_path / "s.db", 1.0, VIDEO_PROVIDER)
    g = HFVideoGen(
        "hf_x",
        spend,
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
        conform_fn=_copy,
    )
    with pytest.raises(VideoGenError):
        await g.generate(request(tmp_path))
    assert spend.used() == 0


async def test_non_json_result_is_a_plain_failure(tmp_path):
    class Html(Server):
        def __call__(self, req):
            r = super().__call__(req)
            if req.method == "GET" and "/status" not in str(req.url) and str(req.url) != CLIP:
                return httpx.Response(200, text="<html>")
            return r

    with pytest.raises(VideoGenError):
        await adapter(Html(), tmp_path).generate(request(tmp_path))


async def test_download_is_retried_because_it_was_paid_for(tmp_path):
    class Once(Server):
        tries = 0

        def __call__(self, req):
            if str(req.url) == CLIP and Once.tries == 0:
                Once.tries = 1
                return httpx.Response(503)
            return super().__call__(req)

    assert (await adapter(Once(), tmp_path).generate(request(tmp_path))).path.exists()


async def test_timeout_counts_toward_budget(tmp_path):
    g = adapter(Server(statuses=("IN_PROGRESS",)), tmp_path, timeout_sec=-1)
    with pytest.raises(VideoGenError, match="오래"):
        await g.generate(request(tmp_path))
    assert g.spend.used() > 0  # 공급자 쪽에서 끝나 과금됐을 수 있다


async def test_big_photo_is_shrunk_before_sending(tmp_path):
    server = Server()

    async def fake_shrink(src, out):
        out.write_bytes(b"small")
        return out

    g = adapter(server, tmp_path, shrink_fn=fake_shrink)
    req = request(tmp_path)
    req.image.write_bytes(b"x" * 3_000_001)
    await g.generate(req)
    assert server.body["image_url"].startswith("data:image/jpeg;base64,")
    assert not list(tmp_path.glob("*.send.jpg"))


def test_video_spend_and_llm_budget_are_separate(tmp_path):
    db = tmp_path / "s.db"
    video = SpendMeter(db, 1.0, VIDEO_PROVIDER)
    llm = SpendMeter(db, 1.0)
    video.record_usd(VIDEO_PROVIDER, "m", "scene_motion", 0, 0, 0.5)
    llm.record_usd("anthropic", "m", "s4_strategy", 1, 1, 0.2)
    assert video.used() == pytest.approx(0.5)
    assert llm.used() == pytest.approx(0.2)


def test_off_by_default_and_needs_a_token():
    assert build_adapters(Settings(_env_file=None), problems=[]).video_gen is None
    problems: list[str] = []
    on = Settings(_env_file=None, video_gen="hf", hf_token="")
    assert build_adapters(on, problems=problems).video_gen is None
    assert any("Hugging Face" in p for p in problems)


async def test_check_token_is_a_free_account_lookup():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200 if "good" in req.headers["authorization"] else 401, json={})

    transport = httpx.MockTransport(handler)
    assert (await check_token("hf_good", transport))[0] is True
    assert (await check_token("hf_bad", transport))[0] is False
    assert all("huggingface.co/api/whoami" in u for u in seen)
    busy = httpx.MockTransport(lambda req: httpx.Response(503))
    assert (await check_token("hf_good", busy))[0] is None  # 서버 문제로 토큰을 거절하지 않는다


@pytest.mark.parametrize(
    ("role", "fine", "ok"),
    [
        ("fineGrained", {"global": [], "scoped": [{"permissions": ["repo.content.read"]}]}, False),
        ("fineGrained", {"global": ["inference.serverless.write"], "scoped": []}, True),
        ("read", None, True),
    ],
)
async def test_token_without_inference_permission_is_refused(role, fine, ok):
    body = {"auth": {"accessToken": {"role": role, "fineGrained": fine}}}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    assert (await check_token("hf_x", transport))[0] is ok


# ── API ─────────────────────────────────────────────────


@pytest.fixture
async def client(orch, store):
    settings = Settings(_env_file=None, data_dir=store.data_dir)
    app = create_app(settings, orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def made(client, orch, sample_input):
    p = orch.create_project(sample_input)
    await orch.run_all(p.id, to_step="s6")
    return orch.store.load(p.id)


async def test_motion_is_refused_when_off(client, orch, sample_input):
    p = await made(client, orch, sample_input)
    r = await client.post(f"/projects/{p.id}/scenes/{p.assets[0].scene_id}/motion")
    assert r.status_code == 400
    assert "설정" in r.json()["detail"]
    assert (await client.get("/config")).json()["video_gen"] is None


async def test_motion_replaces_the_scene_and_can_be_undone(client, orch, sample_input):
    orch.adapters.video_gen = fake = FakeVideoGen()
    p = await made(client, orch, sample_input)
    scene = p.assets[0].scene_id
    still = p.assets[0].image

    r = await client.post(f"/projects/{p.id}/scenes/{scene}/motion")
    assert r.status_code == 200
    body = r.json()["project"]
    image = body["assets"][0]["image"]
    assert image["path"].endswith(".mp4")
    assert image["source"] == "generated"
    assert image["provider"] == "hf:fake"
    assert image["still"]["path"] == still.path
    tl = body["timeline"]["scenes"][0]
    assert tl["image"] == image["path"]
    assert tl["motion"]["type"] == "static"
    assert body["status"]["s6"] == "done"  # 6단계를 다시 돌리지 않고 그 장면만 바뀐다
    assert fake.calls[0].image.name == still.path.rsplit("/", 1)[-1]

    r = await client.post(f"/projects/{p.id}/scenes/{scene}/motion")
    assert r.status_code == 400  # 이미 영상이면 또 돈을 쓰지 않는다
    assert len(fake.calls) == 1

    r = await client.post(f"/projects/{p.id}/scenes/{scene}/motion/revert")
    assert r.status_code == 200
    back = r.json()
    assert back["assets"][0]["image"]["path"] == still.path
    assert back["assets"][0]["image"]["still"] is None
    assert back["timeline"]["scenes"][0]["image"] == still.path
    assert back["timeline"]["scenes"][0]["motion"]["type"] != "static"


async def test_cleanup_keeps_the_original_picture(client, orch, sample_input):
    orch.adapters.video_gen = FakeVideoGen()
    p = await made(client, orch, sample_input)
    scene = p.assets[0].scene_id
    await client.post(f"/projects/{p.id}/scenes/{scene}/motion")
    for old in (orch.store.project_dir(p.id) / "versions").glob("v*.json"):
        old.unlink()  # 버전이 가리켜서 남는 것이 아니라 still이 가리켜서 남아야 한다
    refs = orch.store.referenced_files(p.id)
    assert p.assets[0].image.path in refs


async def test_new_picture_forgets_the_old_original(client, orch, sample_input):
    orch.adapters.video_gen = FakeVideoGen()
    p = await made(client, orch, sample_input)
    scene = p.assets[0].scene_id
    await client.post(f"/projects/{p.id}/scenes/{scene}/motion")
    r = await client.post(f"/projects/{p.id}/scenes/{scene}/image")
    assert r.status_code == 200
    assert r.json()["project"]["assets"][0]["image"]["still"] is None


class Slow(FakeVideoGen):
    """만드는 중 상태를 붙잡아 둔다."""

    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.go = asyncio.Event()

    async def generate(self, req):
        self.started.set()
        await self.go.wait()
        return await super().generate(req)


async def test_same_scene_cannot_be_paid_twice(client, orch, sample_input):
    orch.adapters.video_gen = slow = Slow()
    p = await made(client, orch, sample_input)
    scene = p.assets[0].scene_id
    first = asyncio.create_task(client.post(f"/projects/{p.id}/scenes/{scene}/motion"))
    await slow.started.wait()
    assert (await client.get(f"/projects/{p.id}")).json()["busy"] is True  # 새로고침해도 보인다
    second = await client.post(f"/projects/{p.id}/scenes/{scene}/motion")
    assert second.status_code == 409
    slow.go.set()
    assert (await first).status_code == 200
    assert len(slow.calls) == 1
    still = orch.store.load(p.id).assets[0].image.still
    assert still.path == p.assets[0].image.path


async def test_refreshed_screen_sees_progress_and_failure(client, orch, sample_input):
    class SlowFail(Slow):
        async def generate(self, req):
            self.started.set()
            await self.go.wait()
            raise VideoGenError("지금 서비스가 불안정해요.")

    orch.adapters.video_gen = slow = SlowFail()
    p = await made(client, orch, sample_input)
    scene = p.assets[0].scene_id
    q = orch.bus.subscribe(p.id)
    task = asyncio.create_task(client.post(f"/projects/{p.id}/scenes/{scene}/motion"))
    await slow.started.wait()
    assert (await client.get(f"/projects/{p.id}")).json()["motion_scene"] == scene
    slow.go.set()
    assert (await task).status_code == 502
    after = (await client.get(f"/projects/{p.id}")).json()
    assert after["motion_scene"] is None and after["busy"] is False
    events = [q.get_nowait() for _ in range(q.qsize())]
    assert events[0] == {"type": "motion_started", "scene": scene}
    assert events[-1]["type"] == "motion_finished"
    assert "불안정" in events[-1]["error"]


async def test_conversion_failure_does_not_show_paths(client, orch, sample_input):
    class Broken(FakeVideoGen):
        async def generate(self, req):
            raise MediaError(r"ffmpeg failed C:\Users\me\x.raw.mp4")

    orch.adapters.video_gen = Broken()
    p = await made(client, orch, sample_input)
    r = await client.post(f"/projects/{p.id}/scenes/{p.assets[0].scene_id}/motion")
    assert r.status_code == 502
    assert "Users" not in r.json()["detail"]


async def test_missing_picture_file_is_a_plain_message(client, orch, sample_input):
    orch.adapters.video_gen = fake = FakeVideoGen()
    p = await made(client, orch, sample_input)
    (orch.store.project_dir(p.id) / p.assets[0].image.path).unlink()
    r = await client.post(f"/projects/{p.id}/scenes/{p.assets[0].scene_id}/motion")
    assert r.status_code == 400
    assert fake.calls == []


async def test_render_cannot_cut_in_and_waste_the_clip(client, orch, sample_input):
    orch.adapters.video_gen = slow = Slow()
    p = await made(client, orch, sample_input)
    scene = p.assets[0].scene_id
    task = asyncio.create_task(client.post(f"/projects/{p.id}/scenes/{scene}/motion"))
    await slow.started.wait()
    assert (await client.post(f"/projects/{p.id}/steps/s7/run")).status_code == 409
    assert (await client.post(f"/projects/{p.id}/cleanup")).status_code == 409
    slow.go.set()
    assert (await task).status_code == 200
    assert orch.store.load(p.id).assets[0].image.path.endswith(".mp4")


async def test_other_sites_cannot_spend(client, orch, sample_input):
    orch.adapters.video_gen = fake = FakeVideoGen()
    p = await made(client, orch, sample_input)
    r = await client.post(
        f"/projects/{p.id}/scenes/{p.assets[0].scene_id}/motion",
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert fake.calls == []


async def clip_on(client, orch, p, scene):
    r = await client.post(f"/projects/{p.id}/scenes/{scene}/motion")
    assert r.status_code == 200
    return r.json()["project"]


async def test_voice_change_keeps_a_clip_of_a_listed_photo(client, orch, sample_input, tmp_path):
    orch.adapters.video_gen = FakeVideoGen()
    media = {"user_media": ["media/a.jpg"], "voice": "auto"}
    p = orch.create_project(sample_input.model_copy(update=media))
    photo = orch.store.project_dir(p.id) / "media" / "a.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"\xff\xd8\xff")
    await orch.run_all(p.id, to_step="s6")
    p = orch.store.load(p.id)
    scene = p.assets[0].scene_id
    assert p.assets[0].image.path == "media/a.jpg"
    clip = (await clip_on(client, orch, p, scene))["assets"][0]["image"]["path"]

    inp = orch.store.load(p.id).input.model_copy(update={"voice": "male"})
    await orch.edit(p.id, "input", inp)
    await orch.run_all(p.id, "s5", to_step="s6")
    image = orch.store.load(p.id).assets[0].image
    assert image.path == clip  # 목소리만 바꿨는데 유료 영상이 사라지지 않는다
    assert image.still.path == "media/a.jpg"


async def test_style_change_keeps_a_clip_of_my_own_photo(client, orch, sample_input):
    orch.adapters.video_gen = FakeVideoGen()
    p = await made(client, orch, sample_input)
    scene = p.assets[0].scene_id
    mine = orch.store.project_dir(p.id) / "media" / "me.jpg"
    mine.parent.mkdir(parents=True, exist_ok=True)
    mine.write_bytes(b"\xff\xd8\xff")
    r = await client.post(f"/projects/{p.id}/scenes/{scene}/photo", json={"path": "media/me.jpg"})
    assert r.status_code == 200
    clip = (await clip_on(client, orch, p, scene))["assets"][0]["image"]["path"]

    inp = orch.store.load(p.id).input.model_copy(update={"visual_style": "watercolor"})
    await orch.edit(p.id, "input", inp)
    await orch.run_all(p.id, "s5", to_step="s6")
    image = orch.store.load(p.id).assets[0].image
    assert image.path == clip
    assert image.still.source == "user"


async def test_prompt_rule_change_keeps_a_paid_clip(client, orch, sample_input):
    orch.adapters.video_gen = FakeVideoGen()
    p = await made(client, orch, sample_input)
    scene = p.assets[0].scene_id
    await clip_on(client, orch, p, scene)
    latest = orch.store.load(p.id)
    assets = [a.model_copy(deep=True) for a in latest.assets]
    assets[0].image.rev = 0
    await orch.edit(p.id, "assets", assets)
    await orch.run_all(p.id, "s5", to_step="s6")
    assert orch.store.load(p.id).assets[0].image.path.endswith(".mp4")


async def test_failure_leaves_the_scene_alone(client, orch, sample_input):
    class Broken(FakeVideoGen):
        async def generate(self, req):
            raise VideoGenError("Hugging Face 크레딧이 모자라요.")

    orch.adapters.video_gen = Broken()
    p = await made(client, orch, sample_input)
    scene = p.assets[0].scene_id
    r = await client.post(f"/projects/{p.id}/scenes/{scene}/motion")
    assert r.status_code == 502
    assert "크레딧" in r.json()["detail"]
    assert orch.store.load(p.id).assets[0].image.path == p.assets[0].image.path


async def test_settings_need_consent_and_a_token(orch, store, tmp_path):
    settings = Settings(_env_file=None, data_dir=store.data_dir)
    app = create_app(settings, orch, env_path=tmp_path / ".env")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/settings/video-gen", json={"on": True, "accept_cost": True})
        assert r.status_code == 422  # 토큰 없음
        settings.hf_token = "hf_faketoken"
        r = await c.post("/settings/video-gen", json={"on": True})
        assert r.status_code == 422  # 동의 없음
        r = await c.post(
            "/settings/video-gen",
            json={"on": True, "accept_cost": True, "daily_budget_usd": 2},
        )
        assert r.status_code == 200
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "VIDEO_GEN=hf" in env and "VIDEO_GEN_DAILY_BUDGET_USD=2" in env
        assert "hf_faketoken" not in json.dumps(r.json())
        r = await c.post("/settings/video-gen", json={"on": False})
        assert r.json()["video_gen"]["mode"] == "off"


async def test_kit_discloses_ai_video_and_keeps_photo_checks(orch, store, sample_input):
    orch.adapters.video_gen = FakeVideoGen()
    p = orch.create_project(sample_input)
    await orch.run_all(p.id, to_step="s6")
    p = orch.store.load(p.id)
    a = p.assets[0]
    a.image = a.image.model_copy(
        update={
            "path": "assets/video/S1.mp4",
            "provider": "hf:Lightricks/LTX-2",
            "still": a.image.model_copy(update={"source": "user"}),
        }
    )
    kit = publish_kit(p)
    text = kit["checklist"][0]["text"]
    assert "영상 1개" in text
    assert any(c["id"] == "portrait" for c in kit["checklist"])  # 움직여도 사진 속 사람은 그대로
    assert "Lightricks/LTX-2" in kit["description"]
    assert "영상 1개를 썼다" in text


def test_photo_replaced_on_top_of_a_clip_is_judged_as_a_photo(sample_input):
    from app.schemas.project import Asset, ImageAsset, Project, VoiceAsset

    still = ImageAsset(prompt="p", source="generated", path="assets/a.png")
    image = ImageAsset(prompt="p", source="user", path="media/me.jpg", still=still)
    asset = Asset(scene_id="S1", image=image, voice=VoiceAsset(text="t", voice="v"))
    p = Project(id="prj_000000000000", input=sample_input, assets=[asset])
    assert any(c["id"] == "portrait" for c in publish_kit(p)["checklist"])
