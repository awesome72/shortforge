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


# ── 장면 이미지 다시 만들기 (D12) ─────────────────────────


async def test_regenerate_scene_image(client, adapters):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    p = await wait_idle(client, pid)
    before = p["assets"][2]["image"]

    r = await client.post(f"/projects/{pid}/scenes/S3/image")
    assert r.status_code == 200
    after = r.json()["project"]["assets"][2]["image"]
    assert after["seed"] == before["seed"] + 1
    assert after["path"].startswith(f"assets/S3_{after['seed']}_")
    assert after["path"] != before["path"]
    assert after["provider"] == "fake"
    assert statuses(r.json()["project"]) == ["done"] * 5 + ["stale"] * 2
    assert adapters.image.requests[-1].seed == after["seed"]

    assert (await client.post(f"/projects/{pid}/scenes/S9/image")).status_code == 404


async def test_regenerate_rejected_in_upload_mode(client, orch):
    from app.adapters.image.upload import UploadImageAdapter

    pid = await create(client)
    orch.adapters.image = UploadImageAdapter()
    r = await client.post(f"/projects/{pid}/scenes/S1/image")
    assert r.status_code == 400 and "upload" in r.json()["detail"]


# ── A/B 변형 (F-W6) · 버전 되돌리기 (F-W5) ─────────────────


async def test_duplicate_makes_variant_with_s1_to_s4(client, store):
    pid = await create(client)
    r = await client.post(
        f"/projects/{pid}/media", files=[("files", ("me.jpg", JPEG, "image/jpeg"))]
    )
    await client.post(f"/projects/{pid}/run-all")
    src = await wait_idle(client, pid)

    r = await client.post(f"/projects/{pid}/duplicate")
    assert r.status_code == 201
    b = r.json()
    assert b["id"] != pid and b["parent_id"] == pid and b["variant"] == "B"
    assert statuses(b) == ["done"] * 4 + ["idle"] * 3
    assert b["strategy"] == src["strategy"] and b["assets"] is None and b["render"] is None
    media = b["input"]["user_media"][0]
    assert (store.project_dir(b["id"]) / media).read_bytes() == JPEG  # 사진도 복사됐다

    c = (await client.post(f"/projects/{pid}/duplicate")).json()
    assert c["variant"] == "C"
    rows = {r["id"]: r for r in (await client.get("/projects")).json()}
    assert rows[b["id"]]["parent_id"] == pid and rows[c["id"]]["variant"] == "C"

    # 변형은 S5부터 바로 실행할 수 있다
    assert (
        await client.post(f"/projects/{b['id']}/run-all", params={"from": "s5"})
    ).status_code == 202
    assert statuses(await wait_idle(client, b["id"])) == ["done"] * 7


async def test_versions_list_and_restore(client):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    p = await wait_idle(client, pid)
    original = p["strategy"]["scenes"][1]["line"]
    strategy = p["strategy"]
    strategy["scenes"][1]["line"] = "고친 대사"
    edited = (await client.patch(f"/projects/{pid}/strategy", json=strategy)).json()

    vs = (await client.get(f"/projects/{pid}/versions")).json()
    assert vs[0]["version"] == edited["version"]  # 최신순
    done_all = next(v for v in vs if all(st == "done" for st in v["status"].values()))
    assert done_all["has_render"] and done_all["title"]

    r = await client.post(f"/projects/{pid}/versions/{done_all['version']}/restore")
    assert r.status_code == 200
    restored = r.json()
    assert restored["strategy"]["scenes"][1]["line"] == original
    assert restored["version"] == edited["version"] + 1  # 되돌림도 새 버전
    assert statuses(restored) == ["done"] * 4 + ["stale"] * 3  # 파일은 다시 확인해야 한다
    assert (await client.post(f"/projects/{pid}/versions/9999/restore")).status_code == 404


def test_old_db_gets_new_columns(tmp_path):
    """parent_id·variant 열이 없던 예전 DB도 열리고 목록이 동작한다."""
    import sqlite3

    from app.store import ProjectStore

    data = tmp_path / "data"
    data.mkdir()
    con = sqlite3.connect(data / "shortforge.db")
    con.execute(
        "CREATE TABLE projects (id TEXT PRIMARY KEY, topic TEXT, version INTEGER, updated_at TEXT)"
    )
    con.commit()
    con.close()
    store = ProjectStore(data)
    p = store.create(None)
    assert [r.id for r in store.list()] == [p.id]


# ── 장면 이미지 후보 3개 (F-5.4) · 업로드 체크리스트 ──────


async def test_candidates_then_select(client, store):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    p = await wait_idle(client, pid)
    seed = p["assets"][1]["image"]["seed"]

    r = await client.post(f"/projects/{pid}/scenes/S2/candidates")
    cands = r.json()["candidates"]
    assert [c["seed"] for c in cands] == [seed + 1, seed + 2, seed + 3]
    assert all(c["path"].startswith("assets/candidates/S2_") for c in cands)
    after = (await client.get(f"/projects/{pid}")).json()
    assert after["assets"][1]["image"]["seed"] == seed  # 후보는 아직 적용되지 않는다
    assert statuses(after) == ["done"] * 7

    pick = cands[2]
    picked = store.project_dir(pid) / pick["path"]
    picked.parent.mkdir(parents=True, exist_ok=True)
    picked.write_bytes(JPEG)  # Fake 어댑터는 파일을 만들지 않는다 (실제 어댑터는 만든다)
    r = await client.post(f"/projects/{pid}/scenes/S2/image/select", json=pick)
    assert r.status_code == 200
    applied = r.json()["assets"][1]["image"]
    assert applied["seed"] == seed + 3 and applied["path"] == pick["path"]
    assert statuses(r.json()) == ["done"] * 5 + ["stale"] * 2


async def test_select_rejects_paths_outside_candidates(client, store):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    p = await wait_idle(client, pid)
    (store.data_dir / "shortforge.db").touch()
    for bad in ("../../shortforge.db", "assets/S1", "media/../../../x.jpg"):
        cand = {**p["assets"][0]["image"], "path": bad}
        r = await client.post(f"/projects/{pid}/scenes/S1/image/select", json=cand)
        assert r.status_code == 400, bad


async def test_publish_endpoint(client):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    await wait_idle(client, pid)
    kit = (await client.get(f"/projects/{pid}/publish")).json()
    assert kit["checklist"][0]["id"] == "synthetic" and "#shorts" in kit["description"]


# ── S5 다시 실행: 장면 묘사가 그대로면 이미지를 다시 쓴다 ─────────


async def _rerun_s5(client, pid):
    r = await client.post(f"/projects/{pid}/steps/s5/run")
    assert r.status_code == 202
    return await wait_idle(client, pid)


async def test_s5_rerun_keeps_images_of_unchanged_scenes(client, adapters):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    p = await wait_idle(client, pid)
    before = {a["scene_id"]: a["image"]["path"] for a in p["assets"]}
    generated = len(adapters.image.requests)

    # 대사만 고친다 → 이미지는 그대로, 음성만 다시
    strategy = p["strategy"]
    strategy["scenes"][1]["line"] = "대사만 바꿨다"
    await client.patch(f"/projects/{pid}/strategy", json=strategy)
    p = await _rerun_s5(client, pid)
    assert {a["scene_id"]: a["image"]["path"] for a in p["assets"]} == before
    assert len(adapters.image.requests) == generated
    assert any("이전 이미지를 그대로" in w for w in p["warnings"]["s5"])

    # S3 장면 묘사를 바꾼다 → S3만 새로 만든다
    strategy = p["strategy"]
    strategy["scenes"][2]["visual"] = "완전히 다른 장면"
    await client.patch(f"/projects/{pid}/strategy", json=strategy)
    p = await _rerun_s5(client, pid)
    after = {a["scene_id"]: a["image"]["path"] for a in p["assets"]}
    assert p["assets"][2]["image"]["basis"].startswith("완전히 다른 장면|")
    assert {k: v for k, v in after.items() if k != "S3"} == {
        k: v for k, v in before.items() if k != "S3"
    }
    assert len(adapters.image.requests) == generated + 1


async def test_s5_rerun_images_follow_reordered_scenes(client, adapters):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    p = await wait_idle(client, pid)
    by_visual = {
        s["visual"]: a["image"]["path"]
        for s, a in zip(p["strategy"]["scenes"], p["assets"], strict=True)
    }
    generated = len(adapters.image.requests)

    # 4단계에서 S2와 S3 순서를 바꾸고 번호를 다시 붙인 것과 같다
    strategy = p["strategy"]
    sc = strategy["scenes"]
    sc[1], sc[2] = sc[2], sc[1]
    t = 0.0
    for i, s in enumerate(sc):
        d = s["end"] - s["start"]
        s["id"], s["start"], s["end"] = f"S{i + 1}", t, t + d
        t += d
    await client.patch(f"/projects/{pid}/strategy", json=strategy)
    p = await _rerun_s5(client, pid)
    assert len(adapters.image.requests) == generated
    for s, a in zip(p["strategy"]["scenes"], p["assets"], strict=True):
        assert a["image"]["path"] == by_visual[s["visual"]]


async def test_s5_rerun_keeps_selected_candidate(client, adapters):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    await wait_idle(client, pid)
    cands = (await client.post(f"/projects/{pid}/scenes/S2/candidates?n=2")).json()["candidates"]
    r = await client.post(f"/projects/{pid}/scenes/S2/image/select", json=cands[1])
    assert r.status_code == 200
    p = await _rerun_s5(client, pid)
    assert p["assets"][1]["image"]["path"] == cands[1]["path"]
