"""프로젝트별 이벤트 버스. SSE(GET /projects/{id}/events)가 구독한다."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: defaultdict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, project_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs[project_id].add(q)
        return q

    def unsubscribe(self, project_id: str, q: asyncio.Queue) -> None:
        self._subs[project_id].discard(q)

    async def publish(self, project_id: str, event: dict[str, Any]) -> None:
        for q in list(self._subs[project_id]):
            if q.full():  # 느린 구독자 때문에 파이프라인이 멈추지 않게 가장 오래된 이벤트를 버린다
                q.get_nowait()
            q.put_nowait(event)
