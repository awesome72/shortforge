"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, fileUrl } from "@/lib/api";
import { FREE_TOOLS, ROLE_LABEL, STEPS, STATE_LABEL } from "@/lib/labels";
import { STEP_IDS, type AppConfig, type OutputKey, type Project, type StepId, type StepState } from "@/lib/types";
import { useNarrow } from "@/lib/useNarrow";
import { useProject, type StepProgress } from "@/lib/useProject";
import { CommandPalette, type Command } from "./CommandPalette";
import { SceneMedia, VideoPlayer } from "./Media";
import { ProjectTools } from "./ProjectTools";
import { SetupNotice } from "./SetupNotice";
import type { RunControls } from "./StepActions";
import { S1Input } from "./steps/S1Input";
import { S2Refs } from "./steps/S2Refs";
import { S3Factors } from "./steps/S3Factors";
import { S4Strategy } from "./steps/S4Strategy";
import { S5Assets } from "./steps/S5Assets";
import { S6Timeline } from "./steps/S6Timeline";
import { S7Render } from "./steps/S7Render";
import { Brand, Button, Meter, Notice } from "./ui";
import { Toasts, useToasts } from "./Toast";
import { VersionHistory } from "./VersionHistory";

const IMAGE_MODE_LABEL: Record<string, string> = {
  upload: "본인 사진만",
  stock: "무료 사진",
  "cloudflare,stock": "AI 생성 → 무료 사진",
};

const KEY_OF: Record<StepId, OutputKey> = {
  s1: "input",
  s2: "refs",
  s3: "factors",
  s4: "strategy",
  s5: "assets",
  s6: "timeline",
  s7: "render",
};

export function Workspace({ id }: { id: string }) {
  const router = useRouter();
  const toasts = useToasts();
  const [tab, setTabState] = useState<StepId>("s1");
  // 보고 있는 단계는 주소(#s4)에 둔다: 새로고침해도 그 단계에 머물고, 뒤로 가기와 링크 공유가 된다
  useEffect(() => {
    const sync = () => {
      const hash = window.location.hash.slice(1) as StepId;
      if (STEP_IDS.includes(hash)) setTabState(hash);
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const setTab = (s: StepId) => {
    setTabState(s);
    if (window.location.hash !== `#${s}`) history.pushState(null, "", `#${s}`);
  };
  const [config, setConfig] = useState<AppConfig | null>(null);
  const loadConfig = () =>
    api
      .config()
      .then(setConfig)
      .catch(() => setConfig(null));
  // 단계가 끝나거나 실패하면 알린다. 다른 단계를 보고 있으면 그 단계로 가는 버튼을 붙인다
  const { project, setProject, quota, progress, error, setError, connected } = useProject(id, (e) => {
    const go = (s: StepId) => (s === tab ? undefined : { label: "보기", run: () => setTab(s) });
    // 고급 모드(유료) 사용액을 바로 갱신한다
    if ((e.type === "step_done" || e.type === "step_error") && config?.advanced) loadConfig();
    if (e.type === "step_done")
      toasts.push({ tone: "ok", text: `${STEPS[e.step].n}. ${STEPS[e.step].label} 완료`, action: go(e.step) });
    else if (e.type === "step_error")
      toasts.push({
        tone: "error",
        text: `${STEPS[e.step].n}. ${STEPS[e.step].label}에서 오류가 났어요`,
        action: go(e.step),
      });
    else if (e.type === "run_finished") toasts.push({ tone: "ok", text: "끝까지 실행했어요" });
  });
  const [palette, setPalette] = useState(false);

  const [openKey, setOpenKey] = useState<OutputKey | null>(null);
  // 4·5단계에서 고른 장면. 모니터가 그 장면을 보여 준다
  const [scene, setScene] = useState<string | null>(null);
  const narrow = useNarrow();
  const [dataOpen, setDataOpen] = useState(false);

  useEffect(() => {
    loadConfig();
  }, []);

  // 단축키: 1~7 단계 이동, Ctrl+Enter 이 단계 실행, Ctrl+K 명령 창 (입력칸에 쓰는 중에는 숫자 키를 가로채지 않는다)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      } else if (mod && e.key === "Enter") {
        if (runPrimary()) e.preventDefault();
      } else if (!mod && !e.altKey && !palette && /^[1-7]$/.test(e.key)) {
        const t = e.target as HTMLElement | null;
        if (t?.closest("input, textarea, select, [contenteditable='true']")) return;
        setTab(STEP_IDS[Number(e.key) - 1]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!project) {
    return error ? (
      <div className="p-10">
        <Notice tone="error">{error}</Notice>
      </div>
    ) : (
      <WorkspaceSkeleton />
    );
  }

  const guard = async (fn: () => Promise<unknown>) => {
    try {
      setError(null);
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const controls: RunControls = {
    run: (step) => guard(() => api.runStep(id, step)),
    runFrom: (step) => guard(() => api.runAll(id, step)),
  };
  const save = async <K extends OutputKey>(key: K, value: Project[K]) => {
    await guard(async () => {
      const p = await api.patch(id, key, value);
      setProject((old) => (old ? { ...old, ...p } : old));
      if (key !== "refs") toasts.push({ tone: "info", text: "저장했어요" }); // 레퍼런스 선택은 체크마다 알리지 않는다
    });
  };
  const nextNeeded = STEP_IDS.find((s) => project.status[s] !== "done");
  const commands: Command[] = [
    ...STEP_IDS.map((s) => ({
      id: `go-${s}`,
      group: "이동",
      label: `${STEPS[s].n}. ${STEPS[s].label} — ${STEPS[s].sub}`,
      hint: String(STEPS[s].n),
      run: () => setTab(s),
    })),
    {
      id: "run-step",
      group: "실행",
      label: `지금 단계 실행 (${STEPS[tab].label})`,
      hint: "Ctrl Enter",
      disabled: project.busy,
      run: () => setTimeout(runPrimary, 0),
    },
    {
      id: "run-all",
      group: "실행",
      label: nextNeeded ? `${STEPS[nextNeeded].label}부터 끝까지 실행` : "모든 단계 완료",
      disabled: project.busy || !nextNeeded,
      run: () => nextNeeded && controls.runFrom(nextNeeded),
    },
    { id: "home", group: "이동", label: "홈 (프로젝트 목록)", run: () => router.push("/") },
    {
      id: "settings",
      group: "이동",
      label: "설정 (API 키 · 이미지 방식 · 고급 모드)",
      run: () => router.push("/settings"),
    },
  ];
  const common = { project, controls, save, setTab, guard, config, scene, focusScene: setScene };

  return (
    <div className="flex min-h-screen flex-col">
      {/* ── 상단 바 ── */}
      <header className="sticky top-0 z-20 flex h-[60px] items-center gap-5 border-b border-line bg-surface px-6">
        <Brand />
        <div className="hidden min-w-[160px] flex-1 items-center gap-2 text-[13px] text-muted md:flex">
          <span className="text-faint">/</span>
          {project.variant && (
            <span className="flex-none rounded-full bg-accent-tint px-2 py-px text-[11.5px] font-semibold text-accent">
              변형 {project.variant}
            </span>
          )}
          <b className="truncate font-medium text-ink-2">{project.input?.topic ?? "(주제 없음)"}</b>
          <span className="flex flex-none items-center gap-1.5 text-[12px]">
            <span className={`size-1.5 rounded-full ${connected ? "bg-ok" : "bg-stale"}`} />
            {connected ? `자동 저장됨 · v${project.version}` : "실시간 연결 끊김"}
          </span>
          {project.parent_id && (
            <Link href={`/p/${project.parent_id}`} className="flex-none text-[12px]">
              원본 보기
            </Link>
          )}
        </div>
        <div className="ml-auto flex flex-none items-center gap-3.5">
          {config?.advanced ? (
            <Link
              href="/settings"
              className="inline-flex items-center gap-1.5 rounded-full bg-accent-tint px-2.5 py-[5px] text-[12px] whitespace-nowrap text-accent no-underline hover:text-accent-strong"
              title={`고급 모드(유료): ${config.advanced.tasks.join(", ")}만 ${config.advanced.model}로 처리. 나머지는 무료. UTC ${config.advanced.day_utc} 기준. 눌러서 끄기·예산 설정`}
            >
              <span className="size-1.5 rounded-full bg-accent" />
              <span className="hidden sm:inline">유료 모드</span>
              <span className="hidden 2xl:inline">· {config.advanced.label.split(" (")[0]}</span>
              <span className="tabular-nums">
                ${config.advanced.used_usd.toFixed(2)}
                <span className="hidden md:inline">/${config.advanced.budget_usd.toFixed(2)}</span>
              </span>
            </Link>
          ) : (
            <span className="hidden rounded-full bg-ok-tint px-2.5 py-[5px] text-[12px] whitespace-nowrap text-ok 2xl:inline">
              비용 ₩0 · 무료 스택
            </span>
          )}
          {config && (
            <Link
              href="/settings"
              className={`hidden rounded-full px-2.5 py-[5px] text-[12px] whitespace-nowrap no-underline xl:inline ${config.image_sources.length === 0 && config.image_unused?.length ? "bg-stale-tint text-stale hover:text-stale-strong" : "text-ink-2 shadow-[inset_0_0_0_1px_var(--color-line-strong)] hover:text-ink"}`}
              title={
                config.image_unused?.length
                  ? `${config.image_unused.join("·")} 키가 있는데 쓰지 않고 있다 — 눌러서 설정`
                  : "이미지를 어디서 가져올지 — 눌러서 설정"
              }
            >
              이미지 · {IMAGE_MODE_LABEL[config.image_mode] ?? config.image_mode}
            </Link>
          )}
          {quota?.images && (
            <div className="hidden 2xl:block">
              <Meter
                label="AI 이미지"
                used={quota.images.used}
                limit={quota.images.limit}
                title={`Cloudflare Workers AI 무료 한도 (UTC ${quota.images.day_utc} 기준, 한국 오전 9시 초기화)`}
              />
            </div>
          )}
          {quota && (
            <div className="hidden lg:block">
              <Meter
                label="YouTube 쿼터"
                used={quota.used}
                limit={quota.hard_limit}
                warn={quota.search_blocked}
                title={`태평양 시간 ${quota.day_pt} 기준. 검색은 ${quota.search_limit} units에서 차단`}
              />
            </div>
          )}
          <button
            type="button"
            onClick={() => setPalette(true)}
            className="hidden items-center gap-1.5 rounded-[10px] px-2.5 py-2 text-[12px] text-muted shadow-[inset_0_0_0_1px_var(--color-line-strong)] hover:text-ink md:inline-flex"
            title="명령 창: 단계 이동·실행·설정 (단축키 1~7, Ctrl+Enter)"
          >
            명령 <kbd className="sf-kbd">Ctrl K</kbd>
          </button>
          <Button
            disabled={project.busy || !nextNeeded}
            onClick={() => nextNeeded && controls.runFrom(nextNeeded)}
            title={nextNeeded ? `${STEPS[nextNeeded].label}부터 끝까지` : "모든 단계 완료"}
          >
            <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
              <path d="M4 2.8v10.4a.6.6 0 0 0 .9.5l8.3-5.2a.6.6 0 0 0 0-1L4.9 2.3a.6.6 0 0 0-.9.5z" />
            </svg>
            <span className="hidden sm:inline">
              {project.busy ? "실행 중…" : nextNeeded ? "전체 파이프라인 실행" : "모두 완료"}
            </span>
          </Button>
        </div>
      </header>

      <SetupNotice config={config} />
      {config?.free_tier_notice && <FreeTierNotice model={config.llm_model ?? "Gemini"} />}
      {config?.llm_mode === "fake" && (
        <div className="border-b border-stale-line bg-stale-tint px-6 py-2 text-[12px] text-stale-strong">
          개발 모드: 가짜 LLM(DEV_FAKE_LLM)이라 키워드·요인·전략이 고정 예시로 채워져요.
        </div>
      )}

      {/* ── 파이프라인 타임라인 ── */}
      <PipelineTrack project={project} tab={tab} setTab={setTab} progress={progress} />

      {error && (
        <div className="px-6 pt-4 md:px-10">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      <div className="grid flex-1 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px]">
        <main key={tab} className="sf-step min-w-0 px-4 pt-8 pb-14 md:px-10">
          {tab === "s1" && <S1Input {...common} progress={progress.s1} />}
          {tab === "s2" && <S2Refs {...common} progress={progress.s2} />}
          {tab === "s3" && <S3Factors {...common} progress={progress.s3} />}
          {tab === "s4" && <S4Strategy {...common} progress={progress.s4} />}
          {tab === "s5" && <S5Assets {...common} progress={progress.s5} />}
          {tab === "s6" && <S6Timeline {...common} progress={progress.s6} />}
          {tab === "s7" && <S7Render {...common} progress={progress.s7} />}
        </main>

        {/* ── 인스펙터 ── */}
        <aside
          className="flex min-w-0 flex-col gap-6 border-t border-line bg-surface px-5 pt-6 pb-10 xl:sticky xl:top-[60px] xl:h-[calc(100vh-60px)] xl:self-start xl:overflow-y-auto xl:border-t-0 xl:border-l"
          aria-label="인스펙터"
        >
          <Monitor project={project} tab={tab} scene={scene} narrow={narrow} />

          <section>
            <div className="mb-3 flex items-center justify-between">
              <h4 className="text-[12.5px] font-semibold text-ink-2">단계별 결과</h4>
              {narrow ? (
                <button
                  type="button"
                  onClick={() => setDataOpen((o) => !o)}
                  className="text-[12px] text-muted hover:text-ink"
                >
                  {dataOpen ? "접기" : "펼치기"}
                </button>
              ) : (
                <span className="text-[11.5px] text-faint">Project JSON</span>
              )}
            </div>
            <div className={`overflow-hidden rounded-[10px] border border-line ${narrow && !dataOpen ? "hidden" : ""}`}>
              {STEP_IDS.map((s, i) => {
                const key = KEY_OF[s];
                const value = project[key];
                const state = project.status[s];
                return (
                  <div key={s} className={i > 0 ? "border-t border-line" : ""}>
                    <button
                      type="button"
                      onClick={() => setOpenKey(openKey === key ? null : key)}
                      className={`grid w-full grid-cols-[16px_minmax(0,1fr)_auto] items-center gap-2.5 px-3 py-[9px] text-left text-[12.5px] transition-colors ${tab === s ? "bg-accent-tint" : "bg-surface hover:bg-card"}`}
                    >
                      <StateIcon state={state} />
                      <span className={`truncate ${tab === s ? "text-ink" : "text-ink-2"}`}>
                        {STEPS[s].label}
                        <span className="ml-1.5 font-mono text-[11px] text-faint">
                          {key}
                          {Array.isArray(value) ? `[${value.length}]` : ""}
                        </span>
                      </span>
                      <span className={`text-[11.5px] ${STATE_TEXT[state]}`}>{STATE_LABEL[state]}</span>
                    </button>
                    {openKey === key && (
                      <pre className="max-h-72 overflow-auto border-t border-line bg-sunken p-3 font-mono text-[11px] leading-relaxed text-ink-2">
                        {value ? JSON.stringify(value, null, 2) : "null"}
                      </pre>
                    )}
                  </div>
                );
              })}
            </div>
            <p className="mt-2.5 text-[12px] leading-relaxed text-muted">
              모든 단계가 결과를 한 파일(Project JSON)에 모아요. 앞 단계를 고치면 뒤 단계에 ‘재생성 필요’가 붙어요. 줄을
              누르면 원본을 볼 수 있어요.
            </p>
          </section>

          <section>
            <InsHead title="버전 기록" />
            <VersionHistory key={project.id} project={project} guard={guard} />
          </section>

          <section>
            <InsHead title="관리" />
            <ProjectTools project={project} guard={guard} />
          </section>

          <section>
            <InsHead title="이 단계의 무료 도구" />
            <div className="flex flex-col gap-2.5">
              {FREE_TOOLS[tab].map((t) => (
                <div key={t.name} className="rounded-[10px] border border-line bg-card p-4">
                  <div className="text-[13.5px] leading-snug font-semibold tracking-[-0.01em]">{t.name}</div>
                  <div className="mt-2 text-[12.5px] leading-relaxed text-ink-2">{t.limit}</div>
                  {t.risk !== "—" && (
                    <div className="mt-3 flex gap-2 border-t border-line pt-3 text-[12px] leading-relaxed text-stale-strong">
                      <WarnIcon />
                      <span>{t.risk}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>
      {palette && <CommandPalette commands={commands} onClose={() => setPalette(false)} />}
      <Toasts items={toasts.items} dismiss={toasts.dismiss} />
    </div>
  );
}

/** 본문의 주 실행 버튼(StepActions)을 누른다. 저장 전 처리(beforeRun)와 잠금 조건을 그대로 따른다 */
function runPrimary(): boolean {
  const b = document.querySelector<HTMLButtonElement>("main [data-run-primary]");
  if (!b || b.disabled) return false;
  b.click();
  return true;
}

/** 프로젝트를 불러오는 동안 화면 뼈대만 보여 준다 */
function WorkspaceSkeleton() {
  return (
    <div className="flex min-h-screen flex-col" aria-busy="true" aria-label="불러오는 중">
      <div className="flex h-[60px] items-center gap-5 border-b border-line bg-surface px-6">
        <Brand />
        <span className="sf-skel h-4 w-56" />
        <span className="sf-skel ml-auto h-9 w-40 rounded-[10px]" />
      </div>
      <div className="grid grid-cols-7 gap-1 border-b border-line px-6 pt-10 pb-[18px]">
        {STEP_IDS.map((s) => (
          <span key={s} className="sf-skel h-16 rounded-md" />
        ))}
      </div>
      <div className="grid flex-1 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex flex-col gap-3 px-4 pt-8 md:px-10">
          <span className="sf-skel h-5 w-24" />
          <span className="sf-skel h-8 w-80" />
          <span className="sf-skel h-4 w-[min(560px,100%)]" />
          <span className="sf-skel mt-5 h-48 w-full rounded-[14px]" />
        </div>
        <div className="hidden flex-col gap-4 border-l border-line bg-surface px-5 pt-6 xl:flex">
          <span className="sf-skel mx-auto aspect-[9/16] w-full max-w-[236px] rounded-2xl" />
          <span className="sf-skel h-40 w-full rounded-[10px]" />
        </div>
      </div>
    </div>
  );
}

const STATE_TEXT: Record<StepState, string> = {
  idle: "text-faint",
  running: "text-accent",
  done: "text-ok",
  stale: "text-stale",
  error: "text-err",
};

function InsHead({ title, aside }: { title: string; aside?: string }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h4 className="text-[12.5px] font-semibold text-ink-2">{title}</h4>
      {aside && <span className="text-[11.5px] tabular-nums text-faint">{aside}</span>}
    </div>
  );
}

function StateIcon({ state }: { state: StepState }) {
  if (state === "done")
    return (
      <svg
        viewBox="0 0 16 16"
        width="14"
        height="14"
        className="text-ok"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M3.5 8.5l3 3 6-7" />
      </svg>
    );
  if (state === "running")
    return (
      <svg viewBox="0 0 16 16" width="14" height="14" className="sf-pulse text-accent" aria-hidden="true">
        <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.5" opacity=".35" />
        <path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor" />
      </svg>
    );
  if (state === "error" || state === "stale")
    return (
      <span className={state === "error" ? "text-err" : "text-stale"}>
        <WarnIcon />
      </span>
    );
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" className="text-faint" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2 2" />
    </svg>
  );
}

function WarnIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      className="mt-px flex-none"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M8 1.8L14.6 13.5H1.4z" strokeLinejoin="round" />
      <path d="M8 6.3v3.2M8 11.6v.1" />
    </svg>
  );
}

/** 파이프라인 눈금 자리에 보이는 단계별 결과 요약 (아직 없으면 대시) */
function outputSummary(p: Project, s: StepId): string {
  switch (s) {
    case "s1":
      return p.input?.keywords.length ? `키워드 ${p.input.keywords.length}` : "—";
    case "s2":
      return p.refs ? `레퍼런스 ${p.refs.filter((r) => r.selected).length}/${p.refs.length}` : "—";
    case "s3":
      return p.factors ? `요인 ${p.factors.length}` : "—";
    case "s4":
      return p.strategy
        ? `장면 ${p.strategy.scenes.length} · ${Math.round(p.strategy.scenes.at(-1)?.end ?? 0)}초`
        : "—";
    case "s5":
      return p.assets ? `자산 ${p.assets.length}` : "—";
    case "s6": {
      if (!p.timeline) return "—";
      const t = p.timeline.scenes.reduce((sum, x) => sum + (typeof x.duration === "number" ? x.duration : 0), 0);
      return `${t.toFixed(1)}초`;
    }
    case "s7":
      return p.render ? `MP4 ${p.render.duration_sec.toFixed(1)}초` : "—";
  }
}

/** 7단계를 편집 타임라인의 클립처럼 보여 준다. 플레이헤드가 지금 보고 있는 단계를 가리킨다 */
function PipelineTrack({
  project,
  tab,
  setTab,
  progress,
}: {
  project: Project;
  tab: StepId;
  setTab: (s: StepId) => void;
  progress: Partial<Record<StepId, StepProgress>>;
}) {
  const idx = STEP_IDS.indexOf(tab);
  const navRef = useRef<HTMLElement>(null);
  // 좁은 화면에서는 타임라인이 가로로 스크롤된다. 보고 있는 단계를 가운데로 데려온다
  useEffect(() => {
    const nav = navRef.current;
    const clip = nav?.querySelector<HTMLElement>('[aria-current="step"]');
    if (nav && clip && nav.scrollWidth > nav.clientWidth) {
      nav.scrollTo({ left: clip.offsetLeft - (nav.clientWidth - clip.offsetWidth) / 2, behavior: "smooth" });
    }
  }, [tab]);
  return (
    <nav
      ref={navRef}
      aria-label="제작 단계"
      className="relative overflow-x-auto border-b border-line bg-[linear-gradient(var(--color-surface),var(--color-canvas))] px-4 pt-3.5 pb-[18px] md:px-6"
    >
      <div className="relative min-w-[980px]">
        <div className="mb-2 grid h-[18px] grid-cols-7" aria-hidden="true">
          {STEP_IDS.map((s) => (
            <span key={s} className="truncate border-l border-line-strong pl-1.5 text-[11px] tabular-nums text-faint">
              {outputSummary(project, s)}
            </span>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {STEP_IDS.map((s) => {
            const state = project.status[s];
            const active = s === tab;
            const bar =
              state === "done" ? "bg-ok/70" : state === "stale" ? "bg-stale" : state === "error" ? "bg-err" : "";
            const fill = state === "running" ? Math.max(0.04, progress[s]?.progress ?? 0) : null;
            return (
              <button
                key={s}
                type="button"
                onClick={() => setTab(s)}
                aria-current={active ? "step" : undefined}
                className={`relative flex h-16 flex-col items-start gap-0.5 overflow-hidden rounded-md border px-3 py-2.5 text-left transition-colors ${active ? "border-accent/55 bg-[linear-gradient(180deg,rgba(230,180,96,.16),rgba(230,180,96,.05))]" : state === "done" ? "border-line bg-[#171b21] hover:border-line-strong" : "border-line bg-card hover:border-line-strong"}`}
              >
                {fill !== null && (
                  <span
                    aria-hidden="true"
                    className="absolute inset-y-0 left-0 bg-accent/[.12] transition-[width] duration-700 ease-[cubic-bezier(.2,.7,.2,1)]"
                    style={{ width: `${fill * 100}%` }}
                  />
                )}
                <span className="relative flex w-full items-center gap-2">
                  <span className={`font-mono text-[11px] ${active ? "text-accent" : "text-faint"}`}>
                    {String(STEPS[s].n).padStart(2, "0")}
                  </span>
                  <span
                    className={`text-[13.5px] font-semibold tracking-[-0.01em] whitespace-nowrap ${active ? "text-ink" : "text-ink-2"}`}
                  >
                    {STEPS[s].label}
                  </span>
                  <span className="ml-auto">
                    <StateIcon state={state} />
                  </span>
                </span>
                <span className="relative max-w-full truncate text-[11.5px] text-muted">
                  {fill !== null ? `${progress[s]?.stage ?? "실행 중"} · ${Math.round(fill * 100)}%` : STEPS[s].sub}
                </span>
                {fill !== null ? (
                  <span
                    className="absolute bottom-0 left-0 h-[3px] bg-accent transition-[width] duration-700"
                    style={{ width: `${fill * 100}%` }}
                  />
                ) : (
                  (bar || active) && (
                    <span className={`absolute inset-x-0 bottom-0 h-[3px] ${active ? "bg-accent" : bar}`} />
                  )
                )}
              </button>
            );
          })}
        </div>
        {/* 플레이헤드 */}
        <div
          className="pointer-events-none absolute -top-1 -bottom-1.5 z-[2] w-0 transition-[left] duration-500 ease-[cubic-bezier(.2,.7,.2,1)]"
          style={{ left: `calc(${(idx / 7) * 100}% + ${idx === 0 ? 1 : -2}px)` }}
          aria-hidden="true"
        >
          <span className="absolute top-3.5 bottom-0 -left-px w-0.5 bg-accent shadow-[0_0_12px_rgba(230,180,96,.6)]" />
          <span className="absolute top-1 -left-[7px] h-3 w-3.5 bg-accent [clip-path:polygon(0_0,100%_0,100%_55%,50%_100%,0_55%)]" />
        </div>
      </div>
    </nav>
  );
}

const FREE_TIER_KEY = "sf.freeTierNotice.dismissed";

/** 무료 LLM 등급 안내: 한 줄로 줄이고, 닫으면 같은 모델에서는 다시 띄우지 않는다 (이 브라우저에만 기억) */
function FreeTierNotice({ model }: { model: string }) {
  const [hidden, setHidden] = useState(true); // 기억된 값을 읽기 전에는 숨겨 둔다
  useEffect(() => {
    const read = () => {
      try {
        setHidden(localStorage.getItem(FREE_TIER_KEY) === model);
      } catch {
        setHidden(false);
      }
    };
    read();
  }, [model]);
  if (hidden) return null;
  return (
    <div className="flex items-center gap-2.5 border-b border-line bg-surface px-6 py-1.5 text-[12px] text-muted">
      <span className="flex-none rounded bg-accent-tint px-1.5 py-px text-[11px] font-semibold text-accent">
        무료 등급
      </span>
      <span
        className="min-w-0 truncate"
        title="무료 등급은 입력이 모델 개선에 쓰일 수 있고 상업적 이용이 제외돼요. 민감한 내용은 로컬 모드(LLM_MODE=ollama)로 실행해 주세요."
      >
        {model} · 입력 내용이 모델 개선에 쓰일 수 있고, 상업적 이용은 제외돼요
      </span>
      <button
        type="button"
        onClick={() => {
          setHidden(true);
          try {
            localStorage.setItem(FREE_TIER_KEY, model);
          } catch {}
        }}
        className="ml-auto flex size-6 flex-none items-center justify-center rounded text-faint hover:bg-card hover:text-ink"
        aria-label="무료 등급 안내 닫기"
      >
        <svg
          viewBox="0 0 16 16"
          width="12"
          height="12"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </button>
    </div>
  );
}

/**
 * 9:16 모니터: 보고 있는 단계에 맞춰 바뀐다.
 * 4·5단계는 고른 장면, 렌더가 끝났으면 완성 영상, 2·3·7단계(본문에 영상·표가 있는 곳)는 접어 둔다.
 */
function Monitor({
  project,
  tab,
  scene,
  narrow,
}: {
  project: Project;
  tab: StepId;
  scene: string | null;
  narrow: boolean;
}) {
  // 좁은 화면에서는 인스펙터가 본문 아래에 와서 늘 접어 둔다
  const compactByDefault = narrow || tab === "s2" || tab === "s3" || tab === "s7";
  const [openOn, setOpenOn] = useState<StepId | null>(null);
  const open = !compactByDefault || openOn === tab;
  const focusing = (tab === "s4" || tab === "s5") && scene !== null;
  const video =
    project.render && project.status.s7 === "done" && !focusing
      ? fileUrl(project.id, project.render.path, project.version)
      : null;

  if (!open) {
    return (
      <section>
        <button
          type="button"
          onClick={() => setOpenOn(tab)}
          className="flex w-full items-center justify-between gap-3 rounded-[10px] border border-line bg-card px-3.5 py-2.5 text-left text-[12.5px] text-ink-2 hover:border-line-strong"
        >
          <span className="font-semibold">9:16 미리보기</span>
          <span className="text-[12px] text-muted">{video ? "완성 영상 · 펼치기" : "펼치기"}</span>
        </button>
      </section>
    );
  }
  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h4 className="text-[12.5px] font-semibold text-ink-2">9:16 미리보기</h4>
        <span className="flex items-center gap-2.5 text-[11.5px] tabular-nums text-faint">
          {video ? "완성 영상" : focusing ? `${scene} 장면` : "1080×1920"}
          {compactByDefault && (
            <button type="button" onClick={() => setOpenOn(null)} className="text-muted hover:text-ink">
              접기
            </button>
          )}
        </span>
      </div>
      {video ? (
        <VideoPlayer
          key={video}
          src={video}
          className="mx-auto aspect-[9/16] w-full max-w-[236px] rounded-2xl border border-line-strong"
        />
      ) : (
        <SceneMonitor project={project} scene={focusing ? scene : null} />
      )}
    </section>
  );
}

/** 장면 이미지 위에 대사 자막과 Shorts UI 세이프존을 겹쳐 보여 준다 (장면을 고르지 않았으면 첫 장면) */
function SceneMonitor({ project, scene }: { project: Project; scene: string | null }) {
  const scenes = project.strategy?.scenes ?? [];
  const hook = scenes.find((s) => s.id === scene) ?? scenes[0];
  const first =
    project.assets?.find((a) => a.scene_id === hook?.id && a.image.path) ?? project.assets?.find((a) => a.image.path);
  const img = first ? fileUrl(project.id, first.image.path, project.version) : null;
  const doneCount = STEP_IDS.filter((s) => project.status[s] === "done").length;
  const total = project.timeline?.scenes.reduce((t, s) => t + (typeof s.duration === "number" ? s.duration : 0), 0);
  const length =
    project.render?.duration_sec || total || project.strategy?.scenes.at(-1)?.end || project.input?.duration_sec || 30;
  const fmt = (sec: number) => {
    const s = Math.round(sec);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };
  return (
    <>
      <div className="relative mx-auto aspect-[9/16] w-full max-w-[236px] overflow-hidden rounded-2xl border border-line-strong bg-[radial-gradient(120%_80%_at_30%_15%,#3a3428_0%,#1b1a18_45%,#0c0d10_100%)] shadow-[0_30px_60px_-30px_rgba(0,0,0,.8)]">
        {img && (
          <SceneMedia
            src={img}
            path={first?.image.path}
            play
            className="absolute inset-0 h-full w-full object-cover opacity-80"
          />
        )}
        <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(0,0,0,.35)_0%,transparent_30%,transparent_55%,rgba(0,0,0,.6)_100%)]" />
        <div className="absolute top-[9%] right-[20%] bottom-[22%] left-[6%] rounded border border-dashed border-white/20" />
        <div className="absolute top-[5%] left-[8%] flex items-center gap-1.5 font-mono text-[9.5px] text-white/70">
          <span className="size-1.5 rounded-full bg-accent" />
          {hook ? `${hook.id} · ${ROLE_LABEL[hook.role] ?? hook.role}` : "미리보기"}
        </div>
        <div className="absolute right-[5%] bottom-[24%] flex flex-col gap-3" aria-hidden="true">
          <i className="size-[22px] rounded-full bg-white/15" />
          <i className="size-[22px] rounded-full bg-white/15" />
          <i className="size-[22px] rounded-full bg-white/15" />
        </div>
        {hook ? (
          <div className="absolute right-[22%] bottom-[30%] left-[8%] text-[17px] leading-[1.3] font-extrabold tracking-[-0.03em] text-white [text-shadow:0_2px_12px_rgba(0,0,0,.6)]">
            {hook.line}
          </div>
        ) : (
          <div className="absolute right-[22%] bottom-[30%] left-[8%] text-[12px] text-white/45">
            전략을 만들면 첫 장면 자막이 여기에 보여요
          </div>
        )}
        <div className="absolute right-[8%] bottom-[7%] left-[8%]">
          <div className="h-[3px] rounded-full bg-white/20">
            <i
              className="block h-full rounded-full bg-white transition-[width] duration-700"
              style={{ width: `${(scene && hook ? hook.end / length : doneCount / 7) * 100}%` }}
            />
          </div>
          <div className="mt-1.5 flex justify-between text-[11.5px] font-medium tabular-nums text-white/70">
            {scene && hook ? (
              <>
                <span>
                  {fmt(hook.start)}–{fmt(hook.end)}
                </span>
                <span>{fmt(length)}</span>
              </>
            ) : (
              <>
                <span>{project.render ? "완성" : `${doneCount}/7 단계`}</span>
                <span>{fmt(length)}</span>
              </>
            )}
          </div>
        </div>
      </div>
      <div className="mt-2.5 flex justify-center gap-3.5 text-[11px] text-faint">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 border-t border-dashed border-muted" />
          Shorts UI 세이프존
        </span>
      </div>
    </>
  );
}

export interface StepProps {
  project: Project;
  controls: RunControls;
  save: <K extends OutputKey>(key: K, value: Project[K]) => Promise<void>;
  setTab: (s: StepId) => void;
  guard: (fn: () => Promise<unknown>) => Promise<void>;
  config: AppConfig | null;
  /** 4·5단계에서 고른 장면 ID (모니터에 보인다) */
  scene: string | null;
  focusScene: (id: string) => void;
  progress?: { stage: string; progress: number };
}
