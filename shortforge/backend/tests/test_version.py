"""버전 번호는 pyproject.toml과 app.__version__ 두 곳에 있다. 함께 올려야 한다."""

import tomllib
from pathlib import Path

from app import __version__


def test_version_matches_pyproject():
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))
    assert pyproject["project"]["version"] == __version__
