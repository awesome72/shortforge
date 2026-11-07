"""외부 서버의 일시 오류와 멈추기에 대한 대비 (Edge-TTS 503, 유료 요청 중 멈추기)."""

import asyncio
from pathlib import Path

import aiohttp
import pytest

from app.adapters.llm.advanced.anthropic_api import AnthropicAdapter
from app.adapters.llm.advanced.openai_compat import OpenAICompatAdapter
from app.adapters.tts import edge
from app.spend import SpendMeter


async def test_edge_tts_retries_server_errors(tmp_path, monkeypatch):
    """503(웹소켓 연결 거절)은 OSError가 아니라 다시 시도하지 않고 5단계가 실패했다."""
    calls = []

    async def flaky(self, text, voice, rate, out_path):
        calls.append(1)
        if len(calls) == 1:
            raise aiohttp.WSServerHandshakeError(None, (), status=503, message="busy")
        out_path.write_bytes(b"mp3")
        return [{"text": "안녕", "start": 0.1, "end": 0.8}]

    async def length(path):
        return 1.2

    monkeypatch.setattr(edge.EdgeTTSAdapter, "_stream", flaky)
    monkeypatch.setattr(edge, "probe_duration", length)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(edge.asyncio, "sleep", lambda s: real_sleep(0))
    out = tmp_path / "a.mp3"
    r = await edge.EdgeTTSAdapter().synthesize("안녕", "ko-KR-SunHiNeural", "+0%", out)
    assert len(calls) == 2 and r.duration_sec == 1.2


@pytest.fixture
def spend(tmp_path):
    return SpendMeter(tmp_path / "db.sqlite", daily_budget_usd=1.0)


async def test_stopping_a_paid_request_still_counts_toward_the_budget(spend):
    """응답 전에 멈춰도 공급자는 청구할 수 있다: 상한값으로 하루 예산에 넣는다."""
    a = AnthropicAdapter("sk-test", "claude-opus-5-5", spend=spend)

    async def hang(**kwargs):
        raise asyncio.CancelledError

    a.client.beta.messages.create = hang
    with pytest.raises(asyncio.CancelledError):
        await a._complete("sys", "user " * 100, {"type": "object"})
    assert spend.used() > 0


async def test_stopping_an_openai_request_counts_too(spend):
    a = OpenAICompatAdapter("openai", "sk-oa-test", "gpt-5.6-sol", spend=spend)

    async def hang(*args, **kwargs):
        raise asyncio.CancelledError

    a.client.post = hang
    with pytest.raises(asyncio.CancelledError):
        await a._complete("sys", "user", {"type": "object"})
    assert spend.used() > 0


async def test_upload_while_running_leaves_no_files(orch, store, sample_input):
    """실행 중에 사진을 추가하면 409이고 media/에 파일이 남지 않는다 (코드 리뷰 3)."""
    import httpx

    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(_env_file=None, data_dir=store.data_dir), orch)
    p = orch.create_project(sample_input)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
        b"\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\xdac\xfc\xcf\xc0P\x0f\x00"
        b"\x04\x85\x01\x80\x84\xa9\x8c!\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    async with orch._lock(p.id):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post(
                f"/projects/{p.id}/media", files=[("files", ("a.png", png, "image/png"))]
            )
    assert r.status_code == 409
    media = store.project_dir(p.id) / "media"
    assert not media.exists() or not any(media.iterdir())


async def test_image_chain_state_is_kept_per_run():
    """한 프로젝트의 단계가 끝나도 다른 프로젝트가 건너뛰는 중인 소스 목록을 비우지 않는다."""
    import asyncio

    from app.adapters.base import ImageAdapter, ImageRequest
    from app.adapters.image.chain import MAX_FAILURES, ImageChain
    from app.adapters.run_state import adapter_run

    class Broken(ImageAdapter):
        wants_english_prompts = True
        calls = 0

        async def generate(self, req):
            Broken.calls += 1
            raise RuntimeError("down")

    chain = ImageChain([("demo", Broken())])
    req = ImageRequest(prompt="p", negative="", seed=1, out_path=Path("x.png"))
    y_ready, x_done = asyncio.Event(), asyncio.Event()

    async def project_y():
        with adapter_run():
            for _ in range(MAX_FAILURES):
                await chain.generate(req)  # 두 번 실패하면 이 실행에서는 건너뛴다
            y_ready.set()
            await x_done.wait()
            before = Broken.calls
            await chain.generate(req)
            assert Broken.calls == before  # 다른 프로젝트가 끝나도 계속 건너뛴다
            assert any("demo" in n for n in chain.drain_notices())

    async def project_x():
        with adapter_run():
            await y_ready.wait()
            assert chain.drain_notices() == []  # Y의 알림이 X에 붙지 않는다
            x_done.set()

    await asyncio.gather(project_y(), project_x())


async def test_steps_run_inside_their_own_adapter_state(orch, sample_input):
    """오케스트레이터가 단계를 실행할 때 어댑터 상태를 새로 연다 (프로젝트끼리 섞이지 않게)."""
    from app.adapters import run_state

    seen = []
    real = orch.adapters.llm._s1_keywords

    def spy(user):
        seen.append(run_state._RUN.get())
        return real(user)

    orch.adapters.llm._s1_keywords = spy
    a = orch.create_project(sample_input)
    b = orch.create_project(sample_input)
    await orch.run_step(a.id, "s1")
    await orch.run_step(b.id, "s1")
    assert len(seen) == 2 and all(s is not None for s in seen) and seen[0] is not seen[1]
