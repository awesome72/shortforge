"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AppBar } from "@/components/AppBar";
import { SetupNotice } from "@/components/SetupNotice";
import { STEPS } from "@/lib/labels";
import { Button, Field, Notice, inputClass } from "@/components/ui";
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
    <div className="mx-auto max-w-[1040px] px-6 pt-14 pb-16">
      <span className="rounded bg-accent-tint px-[7px] py-0.5 font-mono text-[12px] text-accent">NEW PROJECT</span>
      <h1 className="mt-4 text-[38px] leading-[1.15] font-bold tracking-[-0.035em]">잘 된 숏폼의 구조를, 내 이야기로.</h1>
      <p className="mt-3 max-w-[62ch] text-[15px] text-ink-2">
        주제와 타깃을 넣으면 최근 잘 된 YouTube 숏폼을 찾아 왜 잘 됐는지 근거와 함께 정리하고, 그 구조로 30초 세로
        영상(MP4 + 자막)을 만들어요. 7단계를 하나의 편집실에서.
      </p>

      <ol className="mt-8 grid grid-cols-2 gap-1 sm:grid-cols-4 lg:grid-cols-7" aria-label="제작 단계">
        {STEP_IDS.map((s) => (
          <li key={s} className="rounded-md border border-line bg-card px-3 py-2.5">
            <span className="font-mono text-[11px] text-faint">{String(STEPS[s].n).padStart(2, "0")}</span>
            <div className="text-[13px] font-semibold text-ink-2">{STEPS[s].label}</div>
            <div className="truncate text-[11.5px] text-muted">{STEPS[s].sub}</div>
          </li>
        ))}
      </ol>

      <form
        className="mt-8 grid grid-cols-2 gap-x-4 gap-y-[18px] rounded-[14px] border border-line bg-surface p-[22px]"
        onSubmit={(e) => {
          e.preventDefault();
          if (topic.trim()) create();
        }}
      >
        <Field label="무엇을 만들고 싶나요?" wide>
          <input
            className={inputClass}
            value={topic}
            placeholder="예: 퇴근 후 10분 홈트로 3개월간 바뀐 점"
            onChange={(e) => setTopic(e.target.value)}
            autoFocus
          />
        </Field>
        <Field label="타깃 시청자" wide>
          <input
            className={inputClass}
            value={audience}
            placeholder="예: 30대 직장인"
            onChange={(e) => setAudience(e.target.value)}
          />
        </Field>
        <div className="col-span-2">
          <Button type="submit" disabled={!topic.trim() || busy}>
            새 프로젝트 시작
          </Button>
        </div>
      </form>

      {error && (
        <div className="mt-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

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
      {rows === null && !error && <p className="px-[18px] py-6 text-muted">불러오는 중…</p>}
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
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={thumb}
                    alt=""
                    loading="lazy"
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
                    <span className="flex gap-[3px]" aria-label={`7단계 중 ${n}단계 완료`}>
                      {STEP_IDS.map((s, i) => (
                        <i
                          key={s}
                          title={`${STEPS[s].n}. ${STEPS[s].label}`}
                          className={`h-1 w-4 rounded-full ${SEG[stages[i] ?? "idle"] ?? SEG.idle}`}
                        />
                      ))}
                    </span>
                    <span className="text-[12px] tabular-nums text-muted">{n === 7 ? "완성" : `${n}/7`}</span>
                  </span>
                </span>
                <span
                  className="flex-none text-right text-[12px] tabular-nums text-muted"
                  title={new Date(r.updated_at).toLocaleString("ko-KR")}
                >
                  {now ? ago(r.updated_at, now) : ""}
                  <span className="ml-2 hidden text-faint sm:inline">v{r.version}</span>
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
                      href={`/p/${r.id}#s7`}
                      className="block px-3.5 py-2 text-[13px] text-ink-2 no-underline hover:bg-surface hover:text-ink"
                    >
                      렌더 단계로 열기
                    </Link>
                    <div className="px-3.5 py-1 font-mono text-[11px] text-faint">{r.id}</div>
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
