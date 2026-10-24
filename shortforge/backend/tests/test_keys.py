"""화면에서 키 넣기·확인 (app/keys.py, /settings/keys). 외부 호출은 가짜 서버로 대체한다."""

import json

import httpx
import pytest

from app import keys
from app.config import Settings
from app.main import create_app

GOOD = "good-key-123456"
BILLED = "billed-key-123456"


def fake_server(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    key = request.url.params.get("key", "")
    if "youtube" in url:
        if key == GOOD:
            return httpx.Response(200, json={"items": []})
        return httpx.Response(400, json={"error": {"message": f"API key not valid ({url})"}})
    if "generativelanguage" in url:
        if key == GOOD:
            return httpx.Response(200, json={"candidates": []})
        if key == BILLED:
            return httpx.Response(402, json={"error": {"message": "billing required"}})
        return httpx.Response(400, json={"error": {"message": "API key not valid"}})
    if "cloudflare" in url:
        if request.headers["authorization"] == f"Bearer {GOOD}":
            return httpx.Response(200, json={"success": True, "result": []})
        return httpx.Response(403, json={"success": False})
    if "pixabay" in url:
        return httpx.Response(200 if key == GOOD else 400, json={"hits": []})
    raise AssertionError(url)


@pytest.fixture
def env_path(tmp_path):
    (tmp_path / ".env.example").write_text(
        "# 주석은 남는다\nYOUTUBE_API_KEY=\nGEMINI_API_KEY=\nIMAGE_MODE=upload\nTTS_MODE=edge\n",
        encoding="utf-8",
    )
    return tmp_path / ".env"


@pytest.fixture
def settings(store):
    return Settings(_env_file=None, data_dir=store.data_dir, youtube_api_key="", gemini_api_key="")


@pytest.fixture
async def client(orch, settings, env_path):
    orch.settings = settings
    app = create_app(settings, orch, env_path=env_path)
    app.state.key_transport = httpx.MockTransport(fake_server)
    rebuilt = []
    app.state.rebuild = lambda a: rebuilt.append(1) or orch.adapters
    app.state.rebuilt = rebuilt
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        c.app = app
        yield c


async def test_status_never_returns_values(client, settings):
    settings.pixabay_api_key = "secret-pixabay-999"
    r = await client.get("/settings/keys")
    body = r.text
    assert r.status_code == 200
    assert "secret-pixabay-999" not in body
    fields = {f["name"]: f["set"] for f in r.json()["fields"]}
    assert fields["PIXABAY_API_KEY"] is True and fields["YOUTUBE_API_KEY"] is False


async def test_check_reports_each_key_and_hides_it(client):
    r = await client.post(
        "/settings/keys/check",
        json={"YOUTUBE_API_KEY": "wrong-key-123456", "GEMINI_API_KEY": GOOD},
    )
    res = r.json()["results"]
    assert res["GEMINI_API_KEY"]["ok"] is True
    assert res["YOUTUBE_API_KEY"]["ok"] is False
    # 오류 메시지에 요청 URL(키 포함)이 들어 있어도 지운다
    assert "wrong-key-123456" not in r.text


async def test_youtube_check_counts_one_unit(client, settings):
    from app.quota import QuotaMeter

    await client.post("/settings/keys/check", json={"YOUTUBE_API_KEY": GOOD})
    assert QuotaMeter(settings.db_path).used() == 1


async def test_save_writes_env_and_applies(client, settings, env_path):
    r = await client.post(
        "/settings/keys",
        json={"values": {"YOUTUBE_API_KEY": GOOD, "PIXABAY_API_KEY": GOOD}, "image_mode": "stock"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["saved"] == ["IMAGE_MODE", "PIXABAY_API_KEY", "YOUTUBE_API_KEY"]
    text = env_path.read_text(encoding="utf-8")
    assert "# 주석은 남는다" in text and "TTS_MODE=edge" in text
    assert f"YOUTUBE_API_KEY={GOOD}" in text and "IMAGE_MODE=stock" in text
    assert f"PIXABAY_API_KEY={GOOD}" in text  # 예시에 없던 항목은 끝에 붙는다
    assert settings.youtube_api_key == GOOD and settings.image_sources == ["stock"]
    assert client.app.state.rebuilt == [1]
    assert GOOD not in r.text


async def test_save_refuses_billed_gemini_key(client, settings, env_path):
    r = await client.post("/settings/keys", json={"values": {"GEMINI_API_KEY": BILLED}})
    assert r.status_code == 422
    assert "결제" in r.json()["results"]["GEMINI_API_KEY"]["message"]
    assert not env_path.exists() and settings.gemini_api_key == ""


async def test_save_keeps_other_lines_of_existing_env(client, env_path):
    env_path.write_text("﻿GEMINI_API_KEY=old\nRENDER_PRESET=medium\n", encoding="utf-8")
    await client.post("/settings/keys", json={"values": {"GEMINI_API_KEY": GOOD}})
    assert env_path.read_text(encoding="utf-8").splitlines() == [
        f"GEMINI_API_KEY={GOOD}",
        "RENDER_PRESET=medium",
    ]


async def test_cloudflare_checks_id_and_token_together(client):
    r = await client.post("/settings/keys/check", json={"CLOUDFLARE_API_TOKEN": GOOD})
    assert r.json()["results"]["CLOUDFLARE_API_TOKEN"]["ok"] is None  # 계정 ID가 없다
    r = await client.post(
        "/settings/keys/check",
        json={"CLOUDFLARE_ACCOUNT_ID": "abcdef123456", "CLOUDFLARE_API_TOKEN": GOOD},
    )
    assert {v["ok"] for v in r.json()["results"].values()} == {True}


@pytest.mark.parametrize(
    "values",
    [{"YOUTUBE_API_KEY": "has space 123456"}, {"YOUTUBE_API_KEY": "a\nIMAGE_MODE=x"}, {"X": "a"}],
)
async def test_rejects_bad_input(client, values):
    r = await client.post("/settings/keys", json={"values": values})
    assert r.status_code == 422


async def test_rejects_other_origin_and_non_json(client, env_path):
    r = await client.post(
        "/settings/keys",
        json={"values": {"YOUTUBE_API_KEY": GOOD}},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    r = await client.post(
        "/settings/keys",
        content=json.dumps({"values": {"YOUTUBE_API_KEY": GOOD}}),
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code in (415, 422)  # FastAPI가 먼저 JSON이 아닌 본문을 거절한다
    assert not env_path.exists()


async def test_image_mode_must_be_offered(client):
    r = await client.post("/settings/keys", json={"values": {}, "image_mode": "comfyui"})
    assert r.status_code == 422


def test_write_env_without_example(tmp_path):
    keys.write_env(tmp_path / ".env", {"YOUTUBE_API_KEY": GOOD})
    assert (tmp_path / ".env").read_text(encoding="utf-8") == f"YOUTUBE_API_KEY={GOOD}\n"


async def test_brand_name_saved_to_env_and_config(client, settings, env_path):
    r = await client.post("/settings/brand", json={"name": " @my{channel}\n "})
    assert r.status_code == 200 and r.json()["brand_name"] == "@mychannel"
    assert "BRAND_NAME=@mychannel" in env_path.read_text(encoding="utf-8")
    assert settings.brand_name == "@mychannel"
    assert (await client.get("/config")).json()["brand_name"] == "@mychannel"
    long = await client.post("/settings/brand", json={"name": "x" * 31})
    assert long.status_code == 422
