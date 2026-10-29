"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { AppBar } from "@/components/AppBar";
import { SceneMedia } from "@/components/Media";
import { SetupNotice } from "@/components/SetupNotice";
import { TrendingGrid } from "@/components/TrendingGrid";
import { STEPS } from "@/lib/labels";
import { Button, Notice, inputClass } from "@/components/ui";
import { api, fileUrl, supportBundleUrl } from "@/lib/api";
import { STEP_IDS, type AppConfig, type ProjectRow, type StepState } from "@/lib/types";

export default function Home() {
  const router = useRouter();
  const [rows, setRows] = useState<ProjectRow[] | null>(null);
  const [topic, setTopic] = useState("");
  const [audience, setAudience] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const topicRef = useRef<HTMLInputElement>(null);

  const remove = async (id: string) => {
    try {
      await api.deleteProject(id);
      setRows((r) => r?.filter((x) => x.id !== id) ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    api.list().then(setRows).catch((e) => setError(e.message));
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  const create = async () => {
    setBusy(true);
    try {
      const p = await api.create({ topic: topic.trim(), audience: audience.trim() });
      // 아이디어 → 대사·그림·음악까지 자동으로 (렌더는 완성 단계에서)
      await api.runAll(p.id, "s1", "s6").catch(() => {}); // 실패하면 화면의 '만들기 시작'으로 다시
      router.push(`/p/${p.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <>
    <AppBar crumb="스튜디오" />
    <SetupNotice config={config} />
    <div className="mx-auto max-w-[1280px] px-4 pt-12 pb-16 sm:px-6">
      <h1 className="text-[34px] leading-[1.15] font-bold tracking-[-0.035em] sm:text-[42px]">어떤 영상을 만들까요?</h1>
      <p className="mt-3 max-w-[62ch] text-[16px] text-ink-2">
        주제를 한 줄로 적거나, 아래에서 요즘 많이 보는 영상을 골라 보세요. 30초 세로 영상을 만들어 드려요.
      </p>

      <form
        className="mt-7 flex max-w-[860px] flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (topic.trim()) create();
        }}
      >
        <div className="flex flex-wrap gap-3">
          <input
            ref={topicRef}
            className={`${inputClass} min-h-14 min-w-0 flex-1 text-[17px]`}
            value={topic}
            placeholder="예: 퇴근 후 10분 홈트로 3개월간 바뀐 점"
            aria-label="만들고 싶은 영상의 주제"
            onChange={(e) => setTopic(e.target.value)}
            autoFocus
          />
          <Button type="submit" className="min-h-14 px-7 text-[16px]" disabled={!topic.trim() || busy}>
            {busy ? "준비 중…" : "만들기"}
          </Button>
        </div>
        <details className="text-[13.5px] text-muted">
          <summary className="cursor-pointer select-none hover:text-ink">누구에게 보여 줄까요? (선택)</summary>
          <input
            className={`${inputClass} mt-2 max-w-[420px]`}
            value={audience}
            placeholder="예: 30대 직장인"
            aria-label="보여 줄 사람"
            onChange={(e) => setAudience(e.target.value)}
          />
        </details>
      </form>

      {error && (
        <div className="mt-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      <TrendingGrid
        onPick={(t) => {
          setTopic(t);
          window.scrollTo({ top: 0, behavior: "smooth" });
          topicRef.current?.focus();
        }}
      />

      <OutdatedRenders onFinished={() => api.list().then(setRows).catch(() => {})} />
      <ProjectList rows={rows} error={error} onDelete={remove} />
      <p className="mt-10 text-[12px] text-muted">
        문제가 생기면{" "}
        <a href={supportBundleUrl()} className="text-accent hover:underline">
          문제 보고용 파일
        </a>
        (로그·환경 정보, API 키 제외)을 받아 피드백과 함께 보내 주세요.
      </p>
    </div>
    </>
  );
}

/** 끝낸 내부 단계 수 → 쉬운 화면의 세 단계 이름 */
function phase(n: number, stopped = false): string {
  if (stopped && n < 7) return "멈춤 · 열어서 다시 시도";
  return n >= 7 ? "완성" : n >= 4 ? "다듬는 중" : n > 0 ? "아이디어 만드는 중" : "시작 전";
}

const SEG: Record<StepState, string> = {
  done: "bg-ok/70",
  stale: "bg-stale",
  error: "bg-err",
  running: "bg-accent sf-pulse",
  idle: "bg-line-strong",
};

/** "3분 전"처럼 읽는다. 일주일이 넘으면 날짜로 */
function ago(iso: string, now: number): string {
  const sec = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (sec < 60) return "방금";
  if (sec < 3600) return `${Math.floor(sec / 60)}분 전`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}시간 전`;
  if (sec < 86400 * 7) return `${Math.floor(sec / 86400)}일 전`;
  return new Date(iso).toLocaleDateString("ko-KR", { year: "numeric", month: "short", day: "numeric" });
}

type Sort = "recent" | "name" | "progress";

/** 예전 방식으로 렌더한 영상을 한꺼번에 새 방식으로 다시 렌더 (7단계만, 한 개씩 차례로) */
function OutdatedRenders({ onFinished }: { onFinished: () => void }) {
  const [state, setState] = useState<Awaited<ReturnType<typeof api.outdatedRenders>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = !!state?.bulk.running;

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const s = await api.outdatedRenders();
        if (!alive) return;
        setState((prev) => {
          if (prev?.bulk.running && !s.bulk.running) onFinished();
          return s;
        });
        if (s.bulk.running) timer = setTimeout(poll, 3000);
      } catch {
        /* 목록이 안 보이면 안내도 띄우지 않는다 */
      }
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 시작할 때와 다시 렌더를 누른 뒤에만 확인한다
  }, [running]);

  if (!state || (!running && state.ids.length === 0 && state.bulk.total === 0)) return null;
  const { bulk } = state;
  const start = async () => {
    setError(null);
    try {
      await api.rerenderOutdated();
      setState({ ...state, bulk: { ...bulk, running: true, total: state.ids.length, done: 0, failed: 0 } });
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className="mt-8">
      <Notice tone={running ? "info" : state.ids.length ? "warn" : "info"}>
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-[220px] flex-1">
            {running ? (
              <>
                <div className="font-semibold">
                  새 방식으로 다시 만들고 있어요 · {bulk.done}/{bulk.total}
                </div>
                <div>한 개씩 차례로 만들어요. 이 화면을 닫아도 계속돼요.</div>
              </>
            ) : state.ids.length ? (
              <>
                <div className="font-semibold">예전 방식으로 만든 영상이 {state.ids.length}개 있어요</div>
                <div>
                  다시 만들면 그동안 고친 자막·색·소리 처리가 모두 들어가요. 마지막 영상 만들기만 다시 하고 AI는
                  쓰지 않아요.
                </div>
              </>
            ) : (
              <div className="font-semibold">
                다시 만들기를 마쳤어요 · {bulk.total - bulk.failed}개 완료
                {bulk.failed ? ` · ${bulk.failed}개는 실패 (그 영상을 열어 확인해 주세요)` : ""}
              </div>
            )}
          </div>
          {!running && state.ids.length > 0 && <Button onClick={start}>모두 다시 만들기</Button>}
        </div>
        {error && <div className="mt-1 text-err">{error}</div>}
      </Notice>
    </div>
  );
}

function ProjectList({
  rows,
  error,
  onDelete,
}: {
  rows: ProjectRow[] | null;
  error: string | null;
  onDelete: (id: string) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("recent");
  const [menu, setMenu] = useState<string | null>(null); // 펼친 메뉴의 프로젝트
  const [armed, setArmed] = useState<string | null>(null); // 브라우저 확인창 대신 두 번 눌러 삭제
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    const t = setInterval(tick, 60_000);
    return () => clearInterval(t);
  }, []);
  // 메뉴 밖을 누르면 닫는다
  useEffect(() => {
    if (!menu) return;
    const close = (e: PointerEvent) => {
      if (!(e.target as Element).closest("[data-menu]")) setMenu(null);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [menu]);

  const done = (r: ProjectRow) => (r.stages ? r.stages.split(",").filter((x) => x === "done").length : 0);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = (rows ?? []).filter((r) => !q || r.topic.toLowerCase().includes(q) || r.id.includes(q));
    if (sort === "name") return [...list].sort((a, b) => a.topic.localeCompare(b.topic, "ko"));
    if (sort === "progress") return [...list].sort((a, b) => done(b) - done(a));
    return list; // 서버가 최근 수정 순으로 준다
  }, [rows, query, sort]);

  return (
    <section className="mt-10 overflow-hidden rounded-[14px] border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-[18px] py-3">
        <h2 className="text-[13.5px] font-semibold">최근 프로젝트</h2>
        <span className="text-[12px] tabular-nums text-muted">{rows ? `${rows.length}개` : ""}</span>
        {rows && rows.length > 0 && (
          <div className="ml-auto flex items-center gap-2">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="주제로 찾기"
              aria-label="프로젝트 찾기"
              className={`${inputClass} min-h-8 w-[180px] px-3 text-[12.5px]`}
            />
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as Sort)}
              aria-label="정렬"
              className={`${inputClass} min-h-8 px-2.5 text-[12.5px]`}
            >
              <option value="recent">최근 수정 순</option>
              <option value="name">이름 순</option>
              <option value="progress">진행 많은 순</option>
            </select>
          </div>
        )}
      </div>
      {rows === null && !error && (
        <ul aria-busy="true" aria-label="불러오는 중">
          {[0, 1, 2].map((k) => (
            <li key={k} className="flex items-center gap-4 border-t border-line px-[18px] py-3 first:border-t-0">
              <span className="sf-skel h-12 w-[27px] flex-none rounded-[5px]" />
              <span className="flex flex-1 flex-col gap-2">
                <span className="sf-skel h-4 w-[min(320px,70%)]" />
                <span className="sf-skel h-1.5 w-[130px]" />
              </span>
            </li>
          ))}
        </ul>
      )}
      {rows?.length === 0 && (
        <p className="px-[18px] py-6 text-muted">아직 프로젝트가 없어요. 위에서 첫 영상을 시작해 보세요.</p>
      )}
      {rows && rows.length > 0 && shown.length === 0 && (
        <p className="px-[18px] py-6 text-muted">&quot;{query}&quot;에 맞는 프로젝트가 없어요.</p>
      )}
      <ul>
        {shown.map((r) => {
          const stages = (r.stages ? r.stages.split(",") : []) as StepState[];
          const n = done(r);
          const thumb = fileUrl(r.id, r.thumb, r.version);
          return (
            <li key={r.id} className="relative flex items-stretch border-t border-line first:border-t-0">
              <Link
                href={`/p/${r.id}`}
                className="flex min-w-0 flex-1 items-center gap-4 px-[18px] py-3 text-ink no-underline transition-colors hover:bg-white/[.02] hover:text-ink"
              >
                {thumb ? (
                  <SceneMedia
                    src={thumb}
                    path={r.thumb}
                    className="h-12 w-[27px] flex-none rounded-[5px] border border-line-strong object-cover"
                  />
                ) : (
                  <span
                    aria-hidden="true"
                    className="h-12 w-[27px] flex-none rounded-[5px] border border-line-strong bg-[linear-gradient(160deg,#3b3226,#0e1014)]"
                  />
                )}
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    {r.variant && (
                      <span className="flex-none rounded-full bg-accent-tint px-1.5 py-px text-[11px] font-semibold text-accent">
                        변형 {r.variant}
                      </span>
                    )}
                    <span className="truncate text-[14px] font-semibold tracking-[-0.01em]">
                      {r.topic || "(주제 없음)"}
                    </span>
                  </span>
                  <span className="mt-1.5 flex items-center gap-2.5">
                    <span className="flex gap-[3px]" aria-label={`진행: ${phase(n, stages.includes("error"))}`}>
                      {STEP_IDS.map((s, i) => (
                        <i
                          key={s}
                          title={`${STEPS[s].n}. ${STEPS[s].label}`}
                          className={`h-1 w-4 rounded-full ${SEG[stages[i] ?? "idle"] ?? SEG.idle}`}
                        />
                      ))}
                    </span>
                    <span className="text-[12px] tabular-nums text-muted">{phase(n, stages.includes("error"))}</span>
                  </span>
                </span>
                <span
                  className="flex-none text-right text-[12px] tabular-nums text-muted"
                  title={new Date(r.updated_at).toLocaleString("ko-KR")}
                >
                  {now ? ago(r.updated_at, now) : ""}
                </span>
              </Link>
              <div data-menu className="relative flex flex-none items-center pr-2">
                <button
                  type="button"
                  onClick={() => {
                    setMenu((m) => (m === r.id ? null : r.id));
                    setArmed(null);
                  }}
                  aria-haspopup="menu"
                  aria-expanded={menu === r.id}
                  aria-label={`${r.topic || r.id} 메뉴`}
                  className="flex size-8 items-center justify-center rounded-md text-faint hover:bg-card hover:text-ink"
                >
                  <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
                    <circle cx="3.5" cy="8" r="1.3" />
                    <circle cx="8" cy="8" r="1.3" />
                    <circle cx="12.5" cy="8" r="1.3" />
                  </svg>
                </button>
                {menu === r.id && (
                  <div
                    role="menu"
                    onKeyDown={(e) => e.key === "Escape" && setMenu(null)}
                    className="absolute top-[calc(50%+18px)] right-2 z-10 w-[200px] overflow-hidden rounded-[10px] border border-line-strong bg-card py-1 shadow-[0_16px_40px_-12px_rgba(0,0,0,.7)]"
                  >
                    <Link
                      role="menuitem"
                      href={`/p/${r.id}/pro`}
                      className="block px-3.5 py-2 text-[13px] text-ink-2 no-underline hover:bg-surface hover:text-ink"
                    >
                      전문가 화면으로 열기
                    </Link>
                    <div className="my-1 border-t border-line" />
                    <button
                      role="menuitem"
                      type="button"
                      autoFocus
                      onClick={async () => {
                        if (armed !== r.id) return setArmed(r.id);
                        setMenu(null);
                        await onDelete(r.id);
                      }}
                      onBlur={() => setArmed((a) => (a === r.id ? null : a))}
                      className={`block w-full px-3.5 py-2 text-left text-[13px] ${armed === r.id ? "bg-err font-semibold text-canvas" : "text-err hover:bg-err-tint"}`}
                    >
                      {armed === r.id ? "한 번 더 눌러 삭제" : "프로젝트 삭제"}
                    </button>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
