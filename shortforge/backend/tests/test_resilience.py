"""외부 서버의 일시 오류와 멈추기에 대한 대비 (Edge-TTS 503, 유료 요청 중 멈추기)."""

import asyncio

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
