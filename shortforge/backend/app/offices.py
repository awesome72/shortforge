"""매물 홍보 모드의 중개사무소 정보. 한 번 넣으면 다음 매물부터 다시 쓴다.

프로젝트 밖(`data/offices.json`)에 두고, 프로젝트를 만들 때 `Input.listing`으로 복사한다.
사무소 정보를 나중에 고쳐도 지난 영상의 내용은 바뀌지 않는다. 법이 넣지 못하게 한
중개보조원 정보는 받지 않는다 (공인중개사법 제18조의2).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from app.schemas.project import Model
from app.store import _atomic_write, read_rows

MAX_OFFICES = 20


class Office(Model):
    office_name: str = Field(min_length=1, max_length=40)
    office_address: str = Field(min_length=1, max_length=80)
    office_phone: str = Field(min_length=1, max_length=20)
    agent_name: str = Field(min_length=1, max_length=20)
    reg_no: str = Field(min_length=1, max_length=30)
    action: str = Field(default="", max_length=40)  # 손님이 할 일 기본값


def _path(data_dir: Path) -> Path:
    return data_dir / "offices.json"


def load(data_dir: Path) -> list[Office]:
    rows = read_rows(_path(data_dir))
    out: list[Office] = []
    for r in rows:
        try:
            out.append(Office.model_validate(r))
        except ValueError:
            continue  # 칸이 바뀐 옛 행 하나 때문에 목록 전체를 잃지 않게 그 행만 건너뛴다
    return out


def delete(data_dir: Path, name: str) -> list[Office]:
    """저장한 사무소를 지운다 (대표 성명·연락처가 계속 남지 않게)."""
    rows = [o for o in load(data_dir) if o.office_name != name]
    body = json.dumps([o.model_dump() for o in rows], ensure_ascii=False, indent=2)
    if _path(data_dir).exists():
        _atomic_write(_path(data_dir), body)
    return rows


def save(data_dir: Path, office: Office) -> list[Office]:
    """같은 이름이면 고치고, 최근에 쓴 사무소를 맨 앞에 둔다."""
    rows = [office, *[o for o in load(data_dir) if o.office_name != office.office_name]]
    rows = rows[:MAX_OFFICES]
    data_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps([o.model_dump() for o in rows], ensure_ascii=False, indent=2)
    _atomic_write(_path(data_dir), body)
    return rows
