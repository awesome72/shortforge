"""어댑터가 실행(단계 하나)마다 따로 두는 상태: 알림과 '이번 실행에서 건너뛸 소스'.

어댑터는 프로젝트 사이에 하나를 같이 쓴다. 알림·소진 목록을 어댑터에 두면 프로젝트 Y가
5단계에서 멈춘 데모 서버를 건너뛰는 중에 프로젝트 X의 2단계가 끝나며 그 목록을 비워,
Y가 다시 장면마다 기다리고
Y의 경고가 X에 붙었다(코드 리뷰 2026-11-07). 오케스트레이터가 단계를 실행할 때 `adapter_run()`으로
새 상태를 열고, 그 안의 호출(TaskGroup 자식 포함)은 같은 상태를 본다. 실행 밖(API의 장면 다시 그리기
등)에서는 어댑터 자신에 둔다.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_RUN: ContextVar[dict | None] = ContextVar("adapter_run", default=None)


def run_state(owner: object) -> dict[str, Any]:
    """owner 어댑터의 이번 실행 상태 (실행 밖이면 owner 자신의 상태)."""
    run = _RUN.get()
    if run is None:
        return owner.__dict__.setdefault("_own_run_state", {})
    return run.setdefault(id(owner), {})


@contextmanager
def adapter_run() -> Iterator[None]:
    token = _RUN.set({})
    try:
        yield
    finally:
        _RUN.reset(token)


class RunNotices:
    """notices를 실행마다 따로 두는 섞어 쓰기용 클래스."""

    @property
    def notices(self) -> list[str]:
        return run_state(self).setdefault("notices", [])

    @notices.setter
    def notices(self, value: list[str]) -> None:
        run_state(self)["notices"] = value
