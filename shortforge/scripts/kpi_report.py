"""KPI 리포트 (PRD §10). 베타 기간에 주 1회 돌린다.

사용법 (shortforge/backend에서):
    uv run python ../scripts/kpi_report.py [--file 다른/metrics.jsonl]
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.kpi import compute  # noqa: E402
from app.metrics import Metrics  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path)
    args = ap.parse_args()
    path = args.file or Settings().data_dir / "metrics.jsonl"
    rows = Metrics(path).read()
    print(f"이벤트 {len(rows)}개 · {path}\n")
    kpis, weekly = compute(rows)

    print(f"{'지표':<12} {'값':>10}  {'비관/기준/낙관':<18} 판정")
    for k in kpis:
        value = "—" if k.value is None else f"{k.value:,.1f}{k.unit}"
        targets = "/".join(f"{t:g}" for t in k.targets)
        print(f"{k.name:<12} {value:>10}  {targets:<18} {k.grade()}  ({k.note})")

    print("\nNorth Star — 주간 완주 프로젝트 수 (MP4 다운로드)")
    for week, n in weekly.items() or [("—", 0)]:
        print(f"  {week}: {n}")
    llm_speed(rows)
    return 0


def llm_speed(rows: list[dict]) -> None:
    """LLM 요청별 속도 (llm_call). waited는 재시도 전에 기다린 시간이다."""
    calls = [r for r in rows if r.get("event") == "llm_call"]
    if not calls:
        return
    print("\nLLM 요청 속도 — 작업·모델별 (sec: 요청 자체, 대기: 재시도 전에 기다린 시간)")
    print(
        f"  {'작업':<18} {'모델':<24} {'횟수':>4} {'실패':>4} "
        f"{'sec 중앙':>8} {'최대':>6} {'최대 대기':>8}"
    )
    groups: dict[tuple[str, str], list[dict]] = {}
    for c in calls:
        groups.setdefault((c.get("task", "?"), c.get("model", "?")), []).append(c)
    for (task, model), cs in sorted(groups.items()):
        secs = [c.get("sec") or 0 for c in cs]
        fails = sum(1 for c in cs if not c.get("ok"))
        # waited는 한 호출 안에서 누적되므로 최댓값이 가장 오래 기다린 호출의 대기다
        wait = max(c.get("waited") or 0 for c in cs)
        print(
            f"  {task:<18} {model:<24} {len(cs):>4} {fails:>4} "
            f"{statistics.median(secs):>8.1f} {max(secs):>6.1f} {wait:>8.0f}"
        )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
