"""KPI 리포트 (PRD §10). 베타 기간에 주 1회 돌린다.

사용법 (shortforge/backend에서):
    uv run python ../scripts/kpi_report.py [--file 다른/metrics.jsonl]
"""

from __future__ import annotations

import argparse
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
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
