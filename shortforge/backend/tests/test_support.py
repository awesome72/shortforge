"""문제 보고 파일과 서버 로그에 비밀값이 남지 않는다."""

import io
import json
import logging
import zipfile

from app.config import Settings
from app.support import bundle, setup_logging

SECRET = "AQ.secret-gemini-key-123456"


def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, gemini_api_key=SECRET, youtube_api_key="")


def test_log_and_bundle_hide_secrets(tmp_path):
    s = settings(tmp_path)
    path = setup_logging(s)
    log = logging.getLogger("app.test")
    log.error("호출 실패 %s", f"https://x/videos?part=id&key={SECRET}&q=1")
    try:
        raise RuntimeError(f"bad key {SECRET}")
    except RuntimeError as e:
        log.error("단계 실패", exc_info=e)
    for h in logging.getLogger("app").handlers:
        h.flush()
    text = path.read_text(encoding="utf-8")
    assert SECRET not in text
    assert "key=[숨김]" in text and "단계 실패" in text and "RuntimeError" in text

    z = zipfile.ZipFile(io.BytesIO(bundle(s, ["YOUTUBE_API_KEY가 비어 있다"])))
    env = json.loads(z.read("environment.json"))
    assert env["settings"]["gemini_api_key"] == "설정됨"
    assert env["settings"]["youtube_api_key"] == "비어 있음"
    assert env["setup_problems"] == ["YOUTUBE_API_KEY가 비어 있다"]
    for name in z.namelist():
        assert SECRET not in z.read(name).decode("utf-8")
    assert "logs/app.log" in z.namelist()


def test_setup_logging_is_idempotent(tmp_path):
    s = settings(tmp_path)
    setup_logging(s)
    setup_logging(s)
    mine = [h for h in logging.getLogger("app").handlers if h.get_name() == "shortforge-file"]
    assert len(mine) == 1
