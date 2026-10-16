"""KPI 집계 (PRD §10). data/metrics.jsonl 이벤트를 지표와 시나리오 목표로 바꾼다."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime


@dataclass
class KPI:
    name: str
    value: float | None
    unit: str
    targets: tuple[float, float, float]  # 비관, 기준, 낙관
    higher_is_better: bool = True
    note: str = ""

    def grade(self) -> str:
        if self.value is None:
            return "데이터 없음"
        pess, base, opt = self.targets
        better = (lambda a, b: a >= b) if self.higher_is_better else (lambda a, b: a <= b)
        if better(self.value, opt):
            return "낙관 달성"
        if better(self.value, base):
            return "기준 달성"
        if better(self.value, pess):
            return "비관 수준"
        return "비관 미달"


def _ts(row: dict) -> datetime:
    return datetime.fromisoformat(row["ts"])


def compute(rows: list[dict]) -> tuple[list[KPI], dict[str, int]]:
    created: dict[str, datetime] = {}
    renders: dict[str, list[datetime]] = defaultdict(list)
    strategy_edits: dict[str, list[datetime]] = defaultdict(list)
    mp4_downloads: dict[str, datetime] = {}
    duplicated_from: set[str] = set()  # A/B 변형을 만든 원본 프로젝트
    units: dict[str, int] = defaultdict(int)
    searched: set[str] = set()
    factors = with_evidence = 0

    for r in sorted(rows, key=_ts):
        pid, ev = r.get("pid"), r.get("event")
        if ev == "project_created":
            created[pid] = _ts(r)
        elif ev == "render_done":
            renders[pid].append(_ts(r))
        elif ev == "edited" and r.get("key") == "strategy":
            strategy_edits[pid].append(_ts(r))
        elif ev == "project_duplicated" and r.get("parent"):
            duplicated_from.add(r["parent"])
        elif ev == "download" and r.get("kind") == "mp4":
            mp4_downloads.setdefault(pid, _ts(r))
        elif ev == "step_done":
            if r.get("step") in ("s2", "s3") and "units" in r:
                units[pid] += int(r["units"])
                searched.add(pid)
            if r.get("step") == "s3":
                factors += int(r.get("factors", 0))
                with_evidence += int(r.get("with_evidence", 0))

    n = len(created)
    completion = len(set(mp4_downloads) & set(created)) / n * 100 if n else None

    minutes = [(renders[p][0] - created[p]).total_seconds() / 60 for p in created if renders.get(p)]
    make_time = statistics.median(minutes) if minutes else None

    rendered = [p for p in created if renders.get(p)]
    # PRD: "렌더 후 S4로 돌아가 A/B 생성" — 같은 프로젝트에서 고쳐 다시 렌더했거나 변형을 만들었다
    regenerated = [
        p
        for p in rendered
        if p in duplicated_from
        or (len(renders[p]) >= 2 and any(t > renders[p][0] for t in strategy_edits.get(p, [])))
    ]
    regen = len(regenerated) / len(rendered) * 100 if rendered else None

    coverage = with_evidence / factors * 100 if factors else None
    per_project_units = statistics.mean(units[p] for p in searched) if searched else None

    kpis = [
        KPI("완주율", completion, "%", (25, 40, 60), note="생성 → MP4 다운로드"),
        KPI("1편 제작 시간", make_time, "분", (30, 15, 8), higher_is_better=False,
            note="생성 → 첫 렌더 (중앙값, 사용자 체감)"),
        KPI("재생성 비율", regen, "%", (10, 25, 40), note="렌더 후 전략을 고쳐 다시 렌더"),
        KPI("근거 커버리지", coverage, "%", (80, 95, 100), note="근거가 있는 요인 비율"),
        KPI("프로젝트당 쿼터", per_project_units, "units", (600, 350, 250),
            higher_is_better=False, note="S2·S3 YouTube units 평균"),
    ]  # fmt: skip

    weekly: dict[str, int] = defaultdict(int)
    for ts in mp4_downloads.values():
        year, week, _ = ts.isocalendar()
        weekly[f"{year}-W{week:02d}"] += 1
    return kpis, dict(sorted(weekly.items()))
