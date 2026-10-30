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
    assert p["render"]["quality"] >= 3 and p["render_outdated"] is False
    assert {c["id"] for c in p["render"]["checks"]} >= {"silence", "caption_width"}

    # 커버: 만들기 전에는 없고, 만들면 업로드 도구에 나온다
    assert (await client.get(f"/projects/{pid}/publish")).json()["cover"] is None
    r = await client.post(f"/projects/{pid}/cover")
    assert r.status_code == 200 and r.json()["cover"].startswith("render/cover_")
    assert (await client.get(f"/projects/{pid}/publish")).json()["cover"] == r.json()["cover"]
    # 커버 문구 직접 고치기: 문구가 바뀌면 새 파일, 비우면 4단계 제목으로
    kit = (await client.get(f"/projects/{pid}/publish")).json()
    assert kit["cover_title"] == p["strategy"]["titles"][0]
    custom = await client.post(f"/projects/{pid}/cover", json={"title": "퇴근 후 / 10분이면 돼요"})
    assert custom.json()["cover_title"] == "퇴근 후 / 10분이면 돼요"
    assert custom.json()["cover"] != r.json()["cover"]
    reset = await client.post(f"/projects/{pid}/cover", json={"title": ""})
    assert reset.json()["cover"] == r.json()["cover"]

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
    # 6단계가 끝나 있으면 편집 지시서의 그 장면도 바로 맞춰 6단계를 다시 하지 않는다(렌더만 필요)
    project = r.json()["project"]
    assert statuses(project) == ["done"] * 6 + ["stale"]
    assert project["timeline"]["scenes"][2]["image"] == after["path"]
    assert project["timeline"]["audio"] == p["timeline"]["audio"]  # 음악은 그대로
    assert adapters.image.requests[-1].seed == after["seed"]

    assert (await client.post(f"/projects/{pid}/scenes/S9/image")).status_code == 404


async def test_scene_photo_replaces_one_scene(client, store):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    p = await wait_idle(client, pid)
    up = await client.post(
        f"/projects/{pid}/media?attach=false",
        files={"files": ("v.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64, "video/mp4")},
    )
    assert up.status_code == 201, up.text
    path = up.json()["saved"][0]
    r = await client.post(f"/projects/{pid}/scenes/S2/photo", json={"path": path})
    assert r.status_code == 200, r.text
    project = r.json()
    assert project["assets"][1]["image"]["source"] == "user"
    assert project["assets"][1]["image"]["path"] == path
    scene = project["timeline"]["scenes"][1]
    assert scene["image"] == path and scene["motion"]["type"] == "static"  # 영상은 움직이지 않는다
    assert statuses(project) == ["done"] * 6 + ["stale"]
    others = [a["image"]["path"] for i, a in enumerate(project["assets"]) if i != 1]
    assert others == [a["image"]["path"] for i, a in enumerate(p["assets"]) if i != 1]
    # 프로젝트 media/ 밖이나 없는 파일은 받지 않는다
    music = store.project_dir(pid) / "media" / "song.mp3"
    music.write_bytes(b"x")
    for bad in (
        "../../shortforge.db",
        "assets/S1.mp3",
        "media/none.jpg",
        "media/song.mp3",
        "C:/Windows/win.ini",
        "media/a\x00.jpg",
    ):
        r = await client.post(f"/projects/{pid}/scenes/S2/photo", json={"path": bad})
        assert r.status_code == 400, bad


async def test_scene_edits_leave_stale_timeline_alone(client, orch):
    """6단계가 '재생성 필요'면 그림·대사 편집이 지시서를 고쳐 done으로 만들지 않는다."""
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    p = await wait_idle(client, pid)
    await client.patch(f"/projects/{pid}/input", json={**p["input"], "visual_style": "watercolor"})
    await client.post(f"/projects/{pid}/run-all?from=s5&to=s5")
    p = await wait_idle(client, pid)
    assert statuses(p)[4:6] == ["done", "stale"]
    before = p["timeline"]

    r = await client.post(f"/projects/{pid}/scenes/S2/line", json={"text": "새로 고친 대사예요"})
    assert r.status_code == 200, r.text
    assert statuses(r.json())[5] == "stale" and r.json()["timeline"] == before
    r = await client.post(f"/projects/{pid}/scenes/S3/image")
    assert statuses(r.json()["project"])[5] == "stale"
    assert r.json()["project"]["timeline"] == before


async def test_video_to_photo_restores_motion(client, orch):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    await wait_idle(client, pid)
    upload = await client.post(
        f"/projects/{pid}/media?attach=false",
        files={"files": ("v.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64, "video/mp4")},
    )
    video = upload.json()["saved"][0]
    r = await client.post(f"/projects/{pid}/scenes/S2/photo", json={"path": video})
    assert r.json()["timeline"]["scenes"][1]["motion"]["type"] == "static"
    r = await client.post(f"/projects/{pid}/scenes/S2/image")  # 다시 AI 그림으로
    assert r.json()["project"]["timeline"]["scenes"][1]["motion"]["type"] == "zoom_in"


async def test_regenerate_keeps_line_changed_while_drawing(client, orch, adapters):
    """그림을 만드는 동안 바뀐 대사를 덮어쓰지 않는다."""
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    await wait_idle(client, pid)
    real = adapters.image.generate

    async def edit_then_draw(req):
        r = await client.post(f"/projects/{pid}/scenes/S1/line", json={"text": "도중에 고친 대사"})
        assert r.status_code == 200, r.text
        return await real(req)

    adapters.image.generate = edit_then_draw
    r = await client.post(f"/projects/{pid}/scenes/S3/image")
    assert r.status_code == 200, r.text
    project = r.json()["project"]
    assert project["strategy"]["scenes"][0]["line"] == "도중에 고친 대사"
    assert project["assets"][0]["voice"]["text"].startswith("도중에 고친 대사")


async def test_config_says_whether_images_can_be_made(client, orch):
    from app.adapters.image.upload import UploadImageAdapter

    assert (await client.get("/config")).json()["can_generate"] is True
    orch.adapters.image = UploadImageAdapter()
    assert (await client.get("/config")).json()["can_generate"] is False


async def test_regenerate_rejected_in_upload_mode(client, orch):
    from app.adapters.image.upload import UploadImageAdapter

    pid = await create(client)
    orch.adapters.image = UploadImageAdapter()
    r = await client.post(f"/projects/{pid}/scenes/S1/image")
    assert r.status_code == 400 and "내 사진" in r.json()["detail"]


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


# ── 프로젝트 삭제·파일 정리·문제 보고 ─────────────────────


async def test_delete_project(client, store):
    pid = await create(client)
    r = await client.delete(f"/projects/{pid}")
    assert r.status_code == 204
    assert (await client.get(f"/projects/{pid}")).status_code == 404
    assert pid not in [p["id"] for p in (await client.get("/projects")).json()]
    assert not store.project_dir(pid).exists()
    assert (await client.delete(f"/projects/{pid}")).status_code == 404


async def test_delete_refused_while_running(client, orch):
    pid = await create(client)
    orch._active.add(pid)  # 실행이 예약된 상태
    try:
        assert (await client.delete(f"/projects/{pid}")).status_code == 409
    finally:
        orch._active.discard(pid)


async def test_cleanup_removes_only_unused_files(client, store):
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    await wait_idle(client, pid)
    cands = (await client.post(f"/projects/{pid}/scenes/S2/candidates?n=2")).json()["candidates"]
    await client.post(f"/projects/{pid}/scenes/S2/image/select", json=cands[0])
    pdir = store.project_dir(pid)
    stray = pdir / "assets" / "old_unused.jpg"
    stray.write_bytes(b"x" * 10)
    p = (await client.get(f"/projects/{pid}")).json()
    in_use = [
        pdir / path
        for a in p["assets"]
        for path in (a["image"]["path"], a["voice"]["path"], a["voice"]["words_path"])
        if path and (pdir / path).exists()
    ]
    assert in_use

    r = await client.post(f"/projects/{pid}/cleanup")
    assert r.status_code == 200
    assert r.json()["removed"] == 2  # 고르지 않은 후보 1개 + 쓰지 않는 파일 1개
    assert not stray.exists()
    assert not (pdir / cands[1]["path"]).exists()
    assert all(f.exists() for f in in_use)


async def test_support_bundle_with_project(client):
    import io
    import zipfile

    pid = await create(client)
    r = await client.get(f"/support/bundle?project={pid}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert {"README.txt", "environment.json", "project/project.json"} <= set(names)
    assert (await client.get("/support/bundle?project=prj_000000000000")).status_code == 404


async def test_scene_video_upload_checks_signature(client):
    """장면 동영상: MP4·MOV·WEBM 시그니처만 받고, 확장자만 맞춘 파일은 거절한다."""
    pid = await create(client)
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    r = await client.post(
        f"/projects/{pid}/media",
        params={"attach": "false"},
        files=[("files", ("clip.mp4", mp4, "video/mp4"))],
    )
    assert r.status_code == 201 and r.json()["saved"][0].endswith(".mp4")
    bad = await client.post(
        f"/projects/{pid}/media",
        params={"attach": "false"},
        files=[("files", ("fake.mp4", JPEG, "video/mp4"))],
    )
    assert bad.status_code == 415 and "동영상" in bad.json()["detail"]


async def test_rerender_outdated_renders_one_by_one(client, orch, store):
    """예전 방식 렌더(quality 0, 자막 파일 흔적 없음)를 찾아 7단계만 차례로 다시 렌더한다."""
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all")
    await wait_idle(client, pid)
    assert (await client.get("/renders/outdated")).json()["ids"] == []  # 방금 렌더 = 최신 방식

    p = store.load(pid)
    p.render.quality = 0  # 값을 남기기 전 렌더처럼
    store.save(p)
    assert (await client.get("/renders/outdated")).json()["ids"] == [pid]

    r = await client.post("/renders/outdated/rerender")
    assert r.status_code == 202 and r.json()["started"] == 1
    for _ in range(200):
        state = (await client.get("/renders/outdated")).json()
        if not state["bulk"]["running"]:
            break
        await asyncio.sleep(0.05)
    assert state["bulk"] == {"running": False, "total": 1, "done": 1, "failed": 0}
    assert state["ids"] == [] and store.load(pid).render.quality >= 3


async def test_trending_puts_shorts_first(client):
    """첫 화면 인기 영상: 숏폼(3분 이하)을 앞에, 같은 무리 안에서는 조회수 순."""
    r = await client.get("/trending")
    assert r.status_code == 200
    videos = r.json()["videos"]
    assert len(videos) == 12 and r.json()["notice"] is None
    shorts = [v["is_short"] for v in videos]
    assert shorts == sorted(shorts, reverse=True)  # True(숏폼)가 먼저
    assert (await client.get("/trending", params={"category": "../x"})).status_code == 400


async def test_run_all_can_stop_before_render(client):
    """쉬운 화면: 아이디어를 넣으면 다듬기 직전(6단계)까지만 자동으로, 렌더는 '완성'에서."""
    pid = await create(client)
    r = await client.post(f"/projects/{pid}/run-all", params={"from": "s1", "to": "s6"})
    assert r.status_code == 202 and r.json()["until"] == "s6"
    p = await wait_idle(client, pid)
    assert statuses(p) == ["done"] * 6 + ["idle"]
    bad = await client.post(f"/projects/{pid}/run-all", params={"from": "s5", "to": "s2"})
    assert bad.status_code == 400


async def test_set_line_remakes_only_that_scene_voice(client, adapters):
    """대사 한 줄을 바꾸면 그 장면 음성만 다시 만들고 대사·음성·지시서를 맞춘다."""
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all", params={"to": "s6"})
    before = await wait_idle(client, pid)
    calls = len(adapters.tts.calls)
    r = await client.post(
        f"/projects/{pid}/scenes/S2/line",
        json={"text": "아주 길게 고친 대사로 바꿔 봅니다 정말로요"},
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert len(adapters.tts.calls) == calls + 1  # 그 장면 하나만
    s2 = next(s for s in p["strategy"]["scenes"] if s["id"] == "S2")
    a2 = next(a for a in p["assets"] if a["scene_id"] == "S2")
    t2 = next(s for s in p["timeline"]["scenes"] if s["id"] == "S2")
    assert s2["line"].startswith("아주 길게") and a2["voice"]["text"].startswith("아주 길게")
    assert t2["caption"]["text"] == a2["voice"]["text"]
    assert t2["duration"] == round(a2["voice"]["duration_sec"] + t2["pad"], 2)
    old = next(s for s in before["timeline"]["scenes"] if s["id"] == "S2")
    assert t2["duration"] != old["duration"]  # 새 음성 길이로 장면 길이가 바뀐다
    assert statuses(p)[:6] == ["done"] * 6
    empty = await client.post(f"/projects/{pid}/scenes/S2/line", json={"text": "🙂"})
    assert empty.status_code == 400


async def test_set_line_errors_keep_the_project_as_it_was(client, adapters, store):
    """대사 바꾸기 실패(만들기 전 409, 없는 장면 404, 음성 실패 502)는 프로젝트를 그대로 둔다."""
    pid = await create(client)
    early = await client.post(f"/projects/{pid}/scenes/S1/line", json={"text": "새 대사"})
    assert early.status_code == 409
    await client.post(f"/projects/{pid}/run-all", params={"to": "s6"})
    before = await wait_idle(client, pid)
    missing = await client.post(f"/projects/{pid}/scenes/S9/line", json={"text": "새 대사"})
    assert missing.status_code == 404

    async def broken(*a, **k):
        raise RuntimeError("TTS down")

    adapters.tts.synthesize = broken
    r = await client.post(f"/projects/{pid}/scenes/S1/line", json={"text": "새 대사"})
    assert r.status_code == 502 and "목소리" in r.json()["detail"]
    after = (await client.get(f"/projects/{pid}")).json()
    assert after["assets"] == before["assets"] and after["version"] == before["version"]


async def test_same_value_edit_does_not_invalidate(client):
    """이미 고른 값을 다시 저장해도(같은 버튼을 또 누름) 뒤 단계를 '재생성 필요'로 만들지 않는다."""
    pid = await create(client)
    await client.post(f"/projects/{pid}/run-all", params={"to": "s6"})
    p = await wait_idle(client, pid)
    r = await client.patch(f"/projects/{pid}/input", json=p["input"])
    assert r.status_code == 200 and statuses(r.json()) == ["done"] * 6 + ["idle"]
    assert r.json()["version"] == p["version"]
