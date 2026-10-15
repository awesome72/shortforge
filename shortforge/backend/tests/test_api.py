"""HTTP API (PROJECT_PROMPT §8). Fake 어댑터, 외부 호출 없음.

SSE는 무한 스트림이라 여기서 다루지 않고 실서버 스모크(scripts/api_smoke.py)로 확인한다.
"""

import asyncio

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.schemas.project import STEP_IDS

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
PNG = b"\x89PNG\r\n\x1a\nfake-png"


@pytest.fixture
def app(orch, store):
    settings = Settings(_env_file=None, data_dir=store.data_dir)
    return create_app(settings, orch)


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def wait_idle(client, pid, timeout=10.0):
    for _ in range(int(timeout / 0.05)):
        p = (await client.get(f"/projects/{pid}")).json()
        if not p["busy"]:
            return p
        await asyncio.sleep(0.05)
    raise AssertionError("실행이 끝나지 않았다")


def statuses(p):
    return [p["status"][s] for s in STEP_IDS]


async def create(client, **extra):
    r = await client.post(
        "/projects", json={"topic": "퇴근 후 10분 홈트", "audience": "30대 직장인", **extra}
    )
    assert r.status_code == 201
    return r.json()["id"]


async def test_create_run_all_and_read(client):
    pid = await create(client)
    p = (await client.get(f"/projects/{pid}")).json()
    assert p["busy"] is False and p["blockers"]["s3"] == ["s1", "s2"]

    r = await client.post(f"/projects/{pid}/run-all", params={"from": "1"})
    assert r.status_code == 202 and r.json()["started"] == "s1"
    p = await wait_idle(client, pid)
    assert statuses(p) == ["done"] * 7
    assert p["render"]["path"] == "render/final.mp4"

    rows = (await client.get("/projects")).json()
    assert [r["id"] for r in rows] == [pid]


async def test_conflicts_return_409(client):
    pid = await create(client)
    r = await client.post(f"/projects/{pid}/steps/s4/run")
    assert r.status_code == 409 and "s1" in r.json()["detail"]

    assert (await client.post(f"/projects/{pid}/run-all")).status_code == 202
    again = await client.post(f"/projects/{pid}/run-all")
    assert again.status_code == 409 and "실행 중" in again.json()["detail"]
    edit = await client.patch(f"/projects/{pid}/input", json={"topic": "x"})
    assert edit.status_code == 409
    await wait_idle(client, pid)


async def test_patch_validates_and_propagates_stale(client):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    p = await wait_idle(client, pid)

    strategy = p["strategy"]
    strategy["scenes"][1]["line"] = "바뀐 대사"
    r = await client.patch(f"/projects/{pid}/strategy", json=strategy)
    assert r.status_code == 200
    assert statuses(r.json()) == ["done"] * 4 + ["stale"] * 3

    bad = await client.patch(f"/projects/{pid}/strategy", json={"titles": ["하나"]})
    assert bad.status_code == 422
    assert (await client.patch(f"/projects/{pid}/nope", json={})).status_code == 422


async def test_upload_photos_only_invalidates_from_s5(client, store):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    await wait_idle(client, pid)

    files = [
        ("files", ("내 사진 1.JPG", JPEG, "image/jpeg")),
        ("files", ("b.png", PNG, "image/png")),
    ]
    r = await client.post(f"/projects/{pid}/media", files=files)
    assert r.status_code == 201
    saved = r.json()["saved"]
    assert len(saved) == 2 and all(s.startswith("media/") for s in saved)
    assert (store.project_dir(pid) / saved[0]).read_bytes() == JPEG

    p = (await client.get(f"/projects/{pid}")).json()
    assert p["input"]["user_media"] == saved
    assert statuses(p) == ["done"] * 4 + ["stale"] * 3  # 사진만 바뀌면 S5부터

    bad = await client.post(
        f"/projects/{pid}/media", files=[("files", ("x.gif", b"GIF", "image/gif"))]
    )
    assert bad.status_code == 415


async def test_scene_photo_replace_upload_does_not_touch_input(client):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    p = await wait_idle(client, pid)
    r = await client.post(
        f"/projects/{pid}/media",
        params={"attach": "false"},
        files=[("files", ("s3.jpg", JPEG, "image/jpeg"))],
    )
    path = r.json()["saved"][0]
    assert r.json()["user_media"] == []
    assets = p["assets"]
    assets[2]["image"] = {**assets[2]["image"], "source": "user", "path": path}
    r = await client.patch(f"/projects/{pid}/assets", json=assets)
    assert statuses(r.json()) == ["done"] * 5 + ["stale"] * 2  # 시나리오 6: S6부터


async def test_changing_topic_invalidates_everything_after_s1(client):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    p = await wait_idle(client, pid)
    inp = {**p["input"], "topic": "다른 주제"}
    r = await client.patch(f"/projects/{pid}/input", json=inp)
    assert statuses(r.json()) == ["done"] + ["stale"] * 6


async def test_files_served_only_inside_project(client, store):
    pid = await create(client)
    pdir = store.project_dir(pid)
    (pdir / "render").mkdir(parents=True, exist_ok=True)
    (pdir / "render" / "final.srt").write_bytes(b"1\n")  # write_text는 Windows에서 CRLF가 된다
    (store.data_dir / "secret.txt").write_text("no", encoding="utf-8")

    ok = await client.get(f"/projects/{pid}/files/render/final.srt")
    assert ok.status_code == 200 and ok.text == "1\n"
    dl = await client.get(f"/projects/{pid}/files/render/final.srt", params={"download": 1})
    assert "attachment" in dl.headers["content-disposition"]
    assert "attachment" not in ok.headers.get("content-disposition", "")
    for evil in ("../../secret.txt", "..%2F..%2Fsecret.txt", "%2E%2E/%2E%2E/secret.txt"):
        r = await client.get(f"/projects/{pid}/files/{evil}")
        assert r.status_code == 404, evil


async def test_unknown_project_and_step(client):
    assert (await client.get("/projects/prj_nope")).status_code == 404
    pid = await create(client)
    assert (await client.post(f"/projects/{pid}/steps/s9/run")).status_code == 404


async def test_config_and_quota(client):
    cfg = (await client.get("/config")).json()
    assert cfg["llm_mode"] == "fake" and cfg["free_tier_notice"] is False
    assert "api_key" not in str(cfg).lower()
    q = (await client.get("/quota")).json()
    assert q["used"] == 0 and q["search_limit"] == 8000


# ── 보안 회귀 (Step 9 리뷰) ───────────────────────────────


async def test_project_id_cannot_escape_data_dir(client, store):
    """pid=".."면 기준 폴더가 data/로 올라가 shortforge.db가 새던 문제."""
    (store.data_dir / "shortforge.db").touch()
    for pid in ("..", "%2E%2E", "prj_../..", "PRJ_0123456789AB", "prj_0123"):
        r = await client.get(f"/projects/{pid}/files/shortforge.db")
        assert r.status_code in (404, 405), pid  # 405: 다른 라우트로 빠짐 — 파일은 안 나간다
        assert b"SQLite" not in r.content, pid
        if "/" not in pid:  # "prj_../.."는 클라이언트가 /projects/(목록)로 정규화한다
            assert (await client.get(f"/projects/{pid}")).status_code == 404, pid
    with pytest.raises(KeyError):
        store.project_dir("..")


async def test_upload_rejects_disguised_file(client):
    pid = await create(client)
    fake = [("files", ("photo.jpg", b"<script>alert(1)</script>", "image/jpeg"))]
    r = await client.post(f"/projects/{pid}/media", files=fake)
    assert r.status_code == 415 and "이미지 파일이 아니다" in r.json()["detail"]
    p = (await client.get(f"/projects/{pid}")).json()
    assert p["input"]["user_media"] == []
