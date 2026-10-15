"""KPI 이벤트 로그 (PRD §10, Step 9-4). 로컬 파일에만 쓴다 — 외부 전송 없음.

data/metrics.jsonl 한 줄에 이벤트 하나. 집계는 scripts/kpi_report.py.

| 이벤트 | 필드 | 쓰는 KPI |
|---|---|---|
| project_created | pid | 완주율 분모, 제작 시간 시작 |
| step_done / step_error | pid, step, sec, (units, factors, with_evidence) | 쿼터 효율, 근거 |
| edited | pid, key | 재생성 비율 |
| render_done | pid, duration_sec | 제작 시간 끝, 재생성 비율 |
| download | pid, kind | 완주율 분자, North Star |
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.schemas.project import utcnow


class Metrics:
    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()

    def log(self, event: str, **fields: Any) -> None:
        if self.path is None:
            return
        row = {"ts": utcnow().isoformat(), "event": event, **fields}
        line = json.dumps(row, ensure_ascii=False, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def read(self) -> list[dict]:
        if self.path is None or not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 쓰다 끊긴 줄은 건너뛴다
        return rows


NULL_METRICS = Metrics(None)
