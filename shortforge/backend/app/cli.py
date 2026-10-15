"""ShortForge CLI — M0 실행 인터페이스 (D2). 웹 UI(Step 6)와 같은 오케스트레이터를 쓴다.

    uv run python -m app.cli new "퇴근 후 10분 홈트" --audience "30대 직장인" --photos D:/photos
    uv run python -m app.cli run prj_xxx                 # 전체 (s1부터)
    uv run python -m app.cli run prj_xxx --from s4       # s4부터 끝까지
    uv run python -m app.cli run prj_xxx --step s2       # 한 단계만
    uv run python -m app.cli status prj_xxx
    uv run python -m app.cli select prj_xxx 1,3,5,6      # 레퍼런스 선택 (S2 목록 번호)
    uv run python -m app.cli set-line prj_xxx S2 "새 대사"
    uv run python -m app.cli set-photo prj_xxx S3 D:/me.jpg
    uv run python -m app.cli show prj_xxx strategy
    uv run python -m app.cli list

개발용: run에 --fake-llm(LLM만 Fake), --fake(전부 Fake)를 붙일 수 있다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.adapters.fake import fake_adapters
from app.adapters.registry import build_adapters
from app.config import Settings
from app.metrics import Metrics
from app.orchestrator import Orchestrator, OrchestratorError
from app.schemas.project import STEP_IDS, Input, Project, StepState
from app.store import ProjectNotFound, ProjectStore

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
STATE_MARK = {
    StepState.IDLE: "·  대기",
    StepState.RUNNING: "…  실행 중",
    StepState.DONE: "✔  완료",
    StepState.STALE: "↻  재생성 필요",
    StepState.ERROR: "✗  오류",
}
STEP_NAME = {
    "s1": "개인 입력",
    "s2": "레퍼런스 탐색",
    "s3": "성공 요인",
    "s4": "제작 전략",
    "s5": "자산 생성",
    "s6": "합성 지시서",
    "s7": "렌더",
}


class CLIError(Exception):
    pass


def expand_photos(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        p = Path(item).expanduser().resolve()
        if p.is_dir():
            out += [str(f) for f in sorted(p.iterdir()) if f.suffix.lower() in IMAGE_EXT]
        elif p.is_file() and p.suffix.lower() in IMAGE_EXT:
            out.append(str(p))
        else:
            raise CLIError(f"사진을 찾을 수 없다: {item}")
    return out


# ── 출력 ─────────────────────────────────────────────────


def print_status(p: Project, store: ProjectStore) -> None:
    topic = p.input.topic if p.input else "(주제 없음)"
    print(f"\n{p.id} · v{p.version} · {topic}")
    for s in STEP_IDS:
        print(f"  {s} {STEP_NAME[s]:<8} {STATE_MARK[p.status[s]]}")
        for w in p.warnings.get(s, []):
            print(f"       ! {w}")
        if s in p.errors:
            print(f"       ✗ {p.errors[s]}")
    if p.render and p.status["s7"] == StepState.DONE:
        d = store.project_dir(p.id)
        print(f"\n  MP4  {d / p.render.path}  ({p.render.duration_sec:g}초)")
        print(f"  SRT  {d / p.render.srt}")


def print_refs(p: Project) -> None:
    if not p.refs:
        return
    print("\n  번호 선택 관련  구독자대비   일평균  길이  제목")
    for i, r in enumerate(p.refs, 1):
        rel = {True: "○", False: "✗", None: " "}[r.relevant]
        ratio = "숨김" if r.ratio_views_per_sub is None else f"{r.ratio_views_per_sub:,.1f}×"
        print(
            f"  {i:>3}  {'✔' if r.selected else ' ':^3}  {rel:^3} {ratio:>9} "
            f"{r.views_per_day:>8,.0f} {r.duration_sec:>4}s  {r.title[:42]}"
        )


# ── 명령 ─────────────────────────────────────────────────


def make_orchestrator(settings: Settings, store: ProjectStore, args) -> Orchestrator:
    # 편집 명령(select·set-line·set-photo)은 외부 호출이 없으므로 키 없이도 동작해야 한다
    if getattr(args, "fake", False) or args.cmd != "run":
        adapters = fake_adapters()
    else:
        adapters = build_adapters(settings, fake_llm=getattr(args, "fake_llm", False))
    return Orchestrator(
        store, adapters, settings, metrics=Metrics(settings.data_dir / "metrics.jsonl")
    )


async def cmd_run(orch: Orchestrator, store: ProjectStore, args) -> int:
    pid = args.project
    q = orch.bus.subscribe(pid)
    stop = asyncio.Event()

    async def printer() -> None:
        last: tuple[str, str] | None = None
        while not (stop.is_set() and q.empty()):
            try:
                e = await asyncio.wait_for(q.get(), timeout=0.2)
            except TimeoutError:
                continue
            t = e["type"]
            if t == "step_started":
                print(f"▶ {e['step']} {STEP_NAME[e['step']]}", flush=True)
            elif t == "step_progress":
                key = (e["step"], e["stage"].split(":")[0])
                pct = int(e["progress"] * 100)
                if key != last or pct in (100,) or pct % 25 == 0:
                    print(f"   {e['stage'][:40]:<40} {pct:>3}%", flush=True)
                last = key
            elif t == "step_done":
                print(f"✔ {e['step']} 완료", flush=True)
            elif t == "step_error":
                print(f"✗ {e['step']} 오류: {e['error']}", flush=True)

    task = asyncio.create_task(printer())
    try:
        if args.step:
            p = await orch.run_step(pid, args.step)
        else:
            p = await orch.run_all(pid, from_step=args.from_step)
    finally:
        stop.set()
        await task
        orch.bus.unsubscribe(pid, q)
    if p.refs and (args.step == "s2" or (not args.step and args.from_step in ("s1", "s2"))):
        print_refs(p)
    print_status(p, store)
    return 0 if all(p.status[s] != StepState.ERROR for s in STEP_IDS) else 1


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shortforge", description="ShortForge 숏폼 제작 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="새 프로젝트")
    n.add_argument("topic")
    n.add_argument("--audience", default="")
    n.add_argument("--tone", choices=["empathetic", "informative", "humor"], default="empathetic")
    n.add_argument("--duration", type=int, choices=[15, 30, 60], default=30)
    n.add_argument("--lang", default="ko")
    n.add_argument("--region", default="KR")
    n.add_argument("--photos", nargs="*", default=[], help="사진 파일 또는 폴더")
    n.add_argument("--keywords", help="쉼표로 구분 (비우면 S1에서 LLM이 만든다)")

    r = sub.add_parser("run", help="단계 실행")
    r.add_argument("project")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--from", dest="from_step", choices=STEP_IDS, default="s1")
    g.add_argument("--step", choices=STEP_IDS)
    r.add_argument("--fake-llm", action="store_true", help="LLM만 Fake (개발용)")
    r.add_argument("--fake", action="store_true", help="모든 어댑터 Fake (개발용)")

    for name, helptext in (("status", "상태"), ("refs", "레퍼런스 목록")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("project")

    sh = sub.add_parser("show", help="Project JSON 보기")
    sh.add_argument("project")
    sh.add_argument("key", nargs="?")

    sel = sub.add_parser("select", help="레퍼런스 선택 (S2 목록 번호, 쉼표 구분)")
    sel.add_argument("project")
    sel.add_argument("numbers")

    sl = sub.add_parser("set-line", help="장면 대사 수정 (S4 편집 → S5 이후 재생성 필요)")
    sl.add_argument("project")
    sl.add_argument("scene")
    sl.add_argument("text")

    sp_ = sub.add_parser("set-photo", help="장면 사진 교체 (S5 편집 → S6 이후 재생성 필요)")
    sp_.add_argument("project")
    sp_.add_argument("scene")
    sp_.add_argument("photo")

    sub.add_parser("list", help="프로젝트 목록")

    args = ap.parse_args(argv)
    settings = Settings()
    store = ProjectStore(settings.data_dir)

    if args.cmd == "list":
        for row in store.list():
            print(f"{row.id}  v{row.version:<4} {row.updated_at:%Y-%m-%d %H:%M}  {row.topic}")
        return 0

    if args.cmd == "new":
        inp = Input(
            topic=args.topic,
            audience=args.audience,
            tone=args.tone,
            duration_sec=args.duration,
            lang=args.lang,
            region=args.region,
            user_media=expand_photos(args.photos),
            keywords=[k.strip() for k in args.keywords.split(",")] if args.keywords else [],
        )
        p = Orchestrator(
            store, fake_adapters(), settings, metrics=Metrics(settings.data_dir / "metrics.jsonl")
        ).create_project(inp)
        print(p.id)
        print(f"  사진 {len(inp.user_media)}장 · 다음: run {p.id}", file=sys.stderr)
        return 0

    p = store.load(args.project)
    if args.cmd == "status":
        print_status(p, store)
        return 0
    if args.cmd == "refs":
        print_refs(p)
        return 0
    if args.cmd == "show":
        data = p.model_dump(mode="json")
        print(json.dumps(data[args.key] if args.key else data, ensure_ascii=False, indent=2))
        return 0

    orch = make_orchestrator(settings, store, args)
    if args.cmd == "run":
        return await cmd_run(orch, store, args)

    if args.cmd == "select":
        if not p.refs:
            raise CLIError("레퍼런스가 없다 — run --step s2 먼저")
        picks = {int(x) for x in args.numbers.split(",") if x.strip()}
        if not picks or not all(1 <= i <= len(p.refs) for i in picks):
            raise CLIError(f"번호는 1~{len(p.refs)} 사이여야 한다")
        refs = [r.model_copy(update={"selected": i in picks}) for i, r in enumerate(p.refs, 1)]
        p = await orch.edit(p.id, "refs", refs)
    elif args.cmd == "set-line":
        if not p.strategy:
            raise CLIError("전략이 없다 — run --step s4 먼저")
        strategy = p.strategy.model_copy(deep=True)
        scene = next((s for s in strategy.scenes if s.id == args.scene), None)
        if scene is None:
            raise CLIError(f"장면 {args.scene}이 없다 ({', '.join(s.id for s in strategy.scenes)})")
        scene.line = args.text
        p = await orch.edit(p.id, "strategy", strategy)
    elif args.cmd == "set-photo":
        if not p.assets:
            raise CLIError("자산이 없다 — run --step s5 먼저")
        photo = expand_photos([args.photo])[0]
        assets = [a.model_copy(deep=True) for a in p.assets]
        target = next((a for a in assets if a.scene_id == args.scene), None)
        if target is None:
            raise CLIError(f"장면 {args.scene}이 없다")
        target.image.source, target.image.path = "user", photo
        p = await orch.edit(p.id, "assets", assets)
    print_status(p, store)
    return 0


def run() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        return asyncio.run(main())
    except (CLIError, OrchestratorError, ProjectNotFound) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(run())
