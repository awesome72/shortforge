"""Step 3 실 API 스모크: 실제 YouTube로 S2(+S3 댓글)를 돌리고 쿼터 사용량을 확인한다.

LLM은 Fake(고정 키워드)다. 실행 1회 약 300~310 units, 같은 날 재실행은 0 units(캐시).

사용법 (shortforge/backend에서):
    uv run python ../scripts/youtube_smoke.py
    uv run python ../scripts/youtube_smoke.py --keywords "퇴근 후 홈트,10분 운동,직장인 루틴" --with-comments
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.base import Adapters  # noqa: E402
from app.adapters.fake import FakeImage, FakeLLM, FakeTTS, FakeVideo  # noqa: E402
from app.adapters.registry import build_youtube  # noqa: E402
from app.config import Settings  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.quota import QuotaMeter  # noqa: E402
from app.schemas.project import Input, StepState  # noqa: E402
from app.store import ProjectStore  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", help="쉼표로 구분 (없으면 FakeLLM 기본 키워드 3개)")
    ap.add_argument("--with-comments", action="store_true", help="S3 댓글 조회까지 (+4 units)")
    args = ap.parse_args()

    settings = Settings()
    quota = QuotaMeter(settings.db_path, settings.youtube_daily_unit_limit)
    yt = build_youtube(settings)
    adapters = Adapters(llm=FakeLLM(), youtube=yt, tts=FakeTTS(), image=FakeImage(), video=FakeVideo())
    store = ProjectStore(settings.data_dir)
    orch = Orchestrator(store, adapters, settings)

    keywords = [k.strip() for k in args.keywords.split(",")] if args.keywords else []
    p = store.create(
        Input(topic="퇴근 후 10분 홈트로 3개월간 바뀐 점", audience="30대 직장인", keywords=keywords)
    )
    p = await orch.run_step(p.id, "s1")
    print("키워드:", p.input.keywords)

    for attempt in ("1회차", "재실행"):
        before = quota.used()
        p = await orch.run_step(p.id, "s2")
        if p.status["s2"] != StepState.DONE:
            print("S2 실패:", p.errors["s2"])
            return 1
        print(f"S2 {attempt}: {quota.used() - before} units")

    print(f"\n{'선택':<4} {'구독자 대비':>10} {'일평균':>9} {'좋아요율':>7} {'길이':>4}  제목")
    for r in p.refs:
        ratio = "숨김" if r.ratio_views_per_sub is None else f"{r.ratio_views_per_sub:,.1f}×"
        print(
            f"{'✔' if r.selected else ' ':<4} {ratio:>10} {r.views_per_day:>9,.0f} "
            f"{r.like_rate:>7.2%} {r.duration_sec:>3}s  {r.title[:40]}"
        )
    if p.warnings.get("s2"):
        print("경고:", p.warnings["s2"])

    if args.with_comments:
        before = quota.used()
        p = await orch.run_step(p.id, "s3")
        print(f"\nS3 댓글 조회: {quota.used() - before} units, 상태 {p.status['s3'].value}")

    await yt.aclose()
    print("\n오늘 쿼터:", quota.summary())
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
