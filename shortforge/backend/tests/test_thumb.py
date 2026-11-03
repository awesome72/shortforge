"""홈 목록의 작은 썸네일 (원본 그림·영상을 그대로 열지 않는다)."""

import subprocess

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.media import MediaError, find_exe

try:
    FFMPEG = find_exe("ffmpeg")
except MediaError:
    FFMPEG = None

needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg 없음")


async def test_no_thumbnail_is_404_without_ffmpeg(orch, store, sample_input):
    p = orch.create_project(sample_input)  # 그림이 아직 없다
    app = create_app(Settings(_env_file=None, data_dir=store.data_dir), orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get(f"/projects/{p.id}/thumb")).status_code == 404
        assert (await c.get("/projects/prj_000000000000/thumb")).status_code == 404


def test_failed_thumbnail_falls_back_to_the_original(tmp_path, monkeypatch):
    from app import main

    src = tmp_path / "assets" / "S1.png"
    src.parent.mkdir()
    src.write_bytes(b"not an image")
    monkeypatch.setattr(main, "find_exe", lambda name: "ffmpeg-없음.exe")
    assert main.thumbnail(tmp_path, src) == src
    assert not list((tmp_path / "thumbs").glob("tmp_*"))  # 임시 파일을 남기지 않는다


@needs_ffmpeg
async def test_home_thumbnail_is_small_and_follows_the_first_scene(orch, store, sample_input):
    p = orch.create_project(sample_input)
    p = await orch.run_all(p.id, to_step="s5")
    first = store.project_dir(p.id) / p.assets[0].image.path
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=864x1536",
         "-frames:v", "1", "-f", "image2", "-c:v", "png", str(first)],
        check=True,
    )  # fmt: skip
    store.save(store.load(p.id))  # 목록 행(썸네일 경로)을 갱신한다
    app = create_app(Settings(_env_file=None, data_dir=store.data_dir), orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(f"/projects/{p.id}/thumb")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert len(r.content) < 10_000  # 작은 JPG
        thumbs = list((store.project_dir(p.id) / "thumbs").glob("thumb_*.jpg"))
        assert len(thumbs) == 1
        # 첫 장면 그림이 바뀌면 새로 만들고 예전 것은 지운다
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=800x800",
             "-frames:v", "1", "-f", "image2", "-c:v", "png", str(first)],
            check=True,
        )  # fmt: skip
        assert (await c.get(f"/projects/{p.id}/thumb")).status_code == 200
        again = list((store.project_dir(p.id) / "thumbs").glob("thumb_*.jpg"))
        assert len(again) == 1 and again != thumbs
        assert (await c.get("/projects/prj_000000000000/thumb")).status_code == 404
