"""코드 리뷰(2026-11-07) 2차 반영: 작은 안전장치들."""

import json
import sys

import pytest

from app import media, offices
from app.adapters.video.ffmpeg import _resolve
from app.adapters.video_gen.hf import result_url_ok
from app.media import MediaError
from app.orchestrator import next_variant


def test_variant_letter_is_the_first_unused_one():
    assert next_variant(set()) == "B"
    assert next_variant({"B", "C"}) == "D"
    assert next_variant({"C"}) == "B"  # B를 지운 뒤 다시 만들어도 C와 겹치지 않는다


def test_broken_office_list_is_kept_aside_not_overwritten(tmp_path):
    (tmp_path / "offices.json").write_text("{깨짐", encoding="utf-8")
    assert offices.load(tmp_path) == []
    kept = list(tmp_path.glob("offices.json.broken-*"))
    assert kept and kept[0].read_text(encoding="utf-8") == "{깨짐"
    assert not (tmp_path / "offices.json").exists()  # 원본은 옮겨졌고 다음 저장이 새로 만든다
    office = offices.Office(
        office_name="a", office_address="b", office_phone="c", agent_name="d", reg_no="e"
    )
    offices.save(tmp_path, office)
    saved = json.loads((tmp_path / "offices.json").read_text(encoding="utf-8"))
    assert saved[0]["office_name"] == "a"


def test_paid_video_result_must_come_from_the_provider():
    assert result_url_ok("https://v3.fal.media/files/x.mp4")
    assert result_url_ok("https://huggingface.co/x.mp4")
    assert not result_url_ok("http://v3.fal.media/x.mp4")  # https만
    assert not result_url_ok("https://evil.example/fal.media.mp4")
    assert not result_url_ok("https://fal.media.evil.example/x.mp4")


def test_web_edits_only_accept_paths_inside_the_project():
    """화면에서 고친 Project JSON은 프로젝트 안 상대 경로만 (CLI 사진은 렌더가 그대로 쓴다)."""
    from fastapi import HTTPException

    from app.main import check_edit_paths

    ok = [{"scene_id": "S1", "image": {"path": "media/a.jpg"}, "voice": {"path": "assets/S1.mp3"}}]
    check_edit_paths("assets", ok)
    for bad in ("../x.png", "C:/Windows/x.png", "/etc/passwd", "media/../../x.png"):
        with pytest.raises(HTTPException):
            check_edit_paths("assets", [{"scene_id": "S1", "image": {"path": bad}, "voice": {}}])
    with pytest.raises(HTTPException):
        check_edit_paths("input", {"user_media": ["D:/photos/a.jpg"]})
    with pytest.raises(HTTPException):
        check_edit_paths("timeline", {"scenes": [], "audio": {"bgm": "../bgm.m4a"}})


def test_render_still_reads_absolute_cli_photos(tmp_path):
    photo = tmp_path / "photos" / "a.jpg"
    assert _resolve(tmp_path / "prj", str(photo)) == photo  # CLI --photos


async def test_media_run_stops_after_its_time_limit():
    with pytest.raises(MediaError, match="끝나지 않아"):
        await media.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)


def test_temporary_lock_does_not_wipe_the_office_list(tmp_path, monkeypatch):
    """잠금 같은 일시 오류는 빈 목록으로 읽지 않는다 (다음 저장이 목록을 덮어쓰지 않게)."""
    from pathlib import Path

    (tmp_path / "offices.json").write_text("[]", encoding="utf-8")
    real = Path.read_text

    def locked(self, *a, **k):
        if self.name == "offices.json":
            raise PermissionError("locked")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", locked)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(PermissionError):
        offices.load(tmp_path)
    assert (tmp_path / "offices.json").exists()  # 옮기지 않는다


def test_one_outdated_row_does_not_drop_the_whole_list(tmp_path):
    good = {"office_name": "a", "office_address": "b", "office_phone": "c", "agent_name": "d",
            "reg_no": "e"}  # fmt: skip
    (tmp_path / "offices.json").write_text(
        json.dumps([good, {"office_name": "old"}]), encoding="utf-8"
    )
    assert [o.office_name for o in offices.load(tmp_path)] == ["a"]
