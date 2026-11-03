"""다른 사이트에서 로컬 API를 건드리지 못하게 막는 검사."""

import httpx
import pytest

from app.config import Settings
from app.guard import host_name
from app.main import create_app


@pytest.fixture
def app(orch, store):
    return create_app(Settings(_env_file=None, data_dir=store.data_dir), orch)


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    ) as c:
        yield c


BODY = {"topic": "퇴근 후 10분 홈트", "audience": "30대 직장인"}


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        ("127.0.0.1:8000", "127.0.0.1"),
        ("LOCALHOST", "localhost"),
        ("[::1]:8000", "::1"),
        ("evil.example:8000", "evil.example"),
        ("", ""),
        ("[::1", ""),
    ],
)
def test_host_name(raw, name):
    assert host_name(raw) == name


async def test_other_site_cannot_change_anything(client):
    r = await client.post("/projects", json=BODY, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert (await client.get("/projects")).json() == []


async def test_sandboxed_page_is_also_blocked(client):
    r = await client.post("/projects", json=BODY, headers={"Origin": "null"})
    assert r.status_code == 403


async def test_multipart_upload_is_covered_too(client):
    p = (await client.post("/projects", json=BODY)).json()
    r = await client.post(
        f"/projects/{p['id']}/media",
        files={"files": ("a.jpg", b"\xff\xd8\xff\xe0x", "image/jpeg")},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


async def test_web_ui_and_scripts_still_work(client):
    web = {"Origin": "http://127.0.0.1:3000"}
    assert (await client.post("/projects", json=BODY, headers=web)).status_code == 201
    assert (await client.post("/projects", json=BODY)).status_code == 201


async def test_preflight_and_reads_are_not_blocked_by_origin(client):
    r = await client.get("/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200
    r = await client.options(
        "/projects",
        headers={"Origin": "http://127.0.0.1:3000", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 200


@pytest.mark.parametrize("method", ["get", "post"])
async def test_rebound_domain_is_blocked_even_for_reads(client, method):
    headers = {"Host": "evil.example:8000"}
    r = await getattr(client, method)("/projects", headers=headers)
    assert r.status_code == 403


async def test_cors_origin_host_is_allowed_automatically(orch, store):
    settings = Settings(
        _env_file=None, data_dir=store.data_dir, cors_origins=["http://studio.local:3000"]
    )
    app = create_app(settings, orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://studio.local:8000"
    ) as c:
        assert (await c.get("/health")).status_code == 200
