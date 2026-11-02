"""소상공인 모드의 가게 정보. 한 번 넣으면 다음 영상부터 다시 쓴다.

프로젝트 밖(`data/shops.json`)에 두고, 프로젝트를 만들 때 `Input.business`로 복사한다.
가게 정보를 나중에 고쳐도 지난 영상의 내용은 바뀌지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from app.schemas.project import Model
from app.store import _atomic_write

MAX_SHOPS = 50


class Shop(Model):
    shop_name: str = Field(min_length=1, max_length=40)
    area: str = Field(default="", max_length=40)
    action: str = Field(default="", max_length=40)  # 손님이 할 일 기본값


def _path(data_dir: Path) -> Path:
    return data_dir / "shops.json"


def load(data_dir: Path) -> list[Shop]:
    try:
        rows = json.loads(_path(data_dir).read_text(encoding="utf-8"))
        return [Shop.model_validate(r) for r in rows]
    except (OSError, ValueError, TypeError):
        return []  # 없거나 깨졌으면 새로 시작한다. 프로젝트에는 영향이 없다


def save(data_dir: Path, shop: Shop) -> list[Shop]:
    """같은 이름이면 고치고, 최근에 쓴 가게를 맨 앞에 둔다."""
    shops = [shop, *[s for s in load(data_dir) if s.shop_name != shop.shop_name]][:MAX_SHOPS]
    data_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps([s.model_dump() for s in shops], ensure_ascii=False, indent=2)
    _atomic_write(_path(data_dir), body)  # 백신·인덱서 잠금을 다시 시도한다
    return shops
