"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, fileUrl } from "@/lib/api";
import { FREE_TOOLS, STEPS, STATE_LABEL } from "@/lib/labels";
import { STEP_IDS, type AppConfig, type OutputKey, type Project, type StepId, type StepState } from "@/lib/types";
import { useProject } from "@/lib/useProject";
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
  const { project, setProject, quota, progress, error, setError, connected } = useProject(id);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [tab, setTab] = useState<StepId>("s1");

  // /p/{id}#s4 처럼 탭을 지정해 들어올 수 있다 (A/B 복제 후 전략 탭으로 이동)
  useEffect(() => {
    const hash = window.location.hash.slice(1) as StepId;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (STEP_IDS.includes(hash)) setTab(hash);
  }, []);
  const [openKey, setOpenKey] = useState<OutputKey | null>(null);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  if (!project) {
    return (
      <div className="p-10">
        {error ? <Notice tone="error">{error}</Notice> : <p className="text-muted">불러오는 중…</p>}
      </div>
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
    });
  };
  const nextNeeded = STEP_IDS.find((s) => project.status[s] !== "done");
  const common = { project, controls, save, setTab, guard, config };

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
              className="hidden rounded-full bg-accent-tint px-2.5 py-[5px] text-[12px] whitespace-nowrap text-accent no-underline hover:text-accent-strong 2xl:inline"
              title={`고급 모드(유료): ${config.advanced.tasks.join(", ")}만 ${config.advanced.model}로 처리. 나머지는 무료. UTC ${config.advanced.day_utc} 기준`}
            >
              고급 · {config.advanced.label.split(" (")[0]} · ${config.advanced.used_usd.toFixed(2)}/$
              {config.advanced.budget_usd.toFixed(2)}
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
      {config?.free_tier_notice && (
        <div className="border-b border-line bg-surface px-6 py-2 text-[12px] text-muted">
          <span className="mr-2 font-mono text-[11px] text-accent">FREE TIER</span>
          무료 LLM 등급({config.llm_model}) 사용 중 — 입력 내용이 모델 개선에 쓰일 수 있고 상업적 이용이 제외된다. 민감한
          내용은 로컬 모드(LLM_MODE=ollama)로 실행한다.
        </div>
      )}
      {config?.llm_mode === "fake" && (
        <div className="border-b border-stale-line bg-stale-tint px-6 py-2 text-[12px] text-stale-strong">
          개발 모드: LLM이 Fake다 (DEV_FAKE_LLM). 키워드·요인·전략은 고정 예시로 채워진다.
        </div>
      )}

      {/* ── 파이프라인 타임라인 ── */}
      <PipelineTrack project={project} tab={tab} setTab={setTab} />

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
          className="flex min-w-0 flex-col gap-6 border-t border-line bg-surface px-5 pt-6 pb-10 xl:border-t-0 xl:border-l"
          aria-label="인스펙터"
        >
          <section>
            <InsHead title="9:16 미리보기" aside="1080×1920" />
            <Monitor project={project} />
          </section>

          <section>
            <InsHead title="Project JSON" aside="단계 간 공유 컨텍스트" />
            <div className="overflow-hidden rounded-[10px] border border-line">
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
                      <span className={`font-mono text-[12px] ${tab === s ? "text-ink" : "text-ink-2"}`}>
                        {key}
                        {Array.isArray(value) ? `[${value.length}]` : ""}
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
              모든 단계가 같은 Project JSON을 읽고 씁니다. 앞 단계를 고치면 뒤 단계에 ‘재생성 필요’ 표시가 붙습니다.
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
      {aside && <span className="font-mono text-[11px] text-faint">{aside}</span>}
    </div>
  );
}

function StateIcon({ state }: { state: StepState }) {
  if (state === "done")
    return (
      <svg viewBox="0 0 16 16" width="14" height="14" className="text-ok" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
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
    <svg viewBox="0 0 16 16" width="14" height="14" className="mt-px flex-none" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
      <path d="M8 1.8L14.6 13.5H1.4z" strokeLinejoin="round" />
      <path d="M8 6.3v3.2M8 11.6v.1" />
    </svg>
  );
}

/** 7단계를 편집 타임라인의 클립처럼 보여 준다. 플레이헤드가 지금 보고 있는 단계를 가리킨다 */
function PipelineTrack({ project, tab, setTab }: { project: Project; tab: StepId; setTab: (s: StepId) => void }) {
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
          {STEP_IDS.map((s, i) => (
            <span key={s} className="border-l border-line-strong pl-1.5 font-mono text-[10.5px] text-faint">
              00:{String(i).padStart(2, "0")}
            </span>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {STEP_IDS.map((s) => {
            const state = project.status[s];
            const active = s === tab;
            const bar =
              state === "done"
                ? "bg-ok/70"
                : state === "stale"
                  ? "bg-stale"
                  : state === "error"
                    ? "bg-err"
                    : state === "running"
                      ? "bg-accent sf-pulse"
                      : "";
            return (
              <button
                key={s}
                type="button"
                onClick={() => setTab(s)}
                aria-current={active ? "step" : undefined}
                className={`relative flex h-16 flex-col items-start gap-0.5 overflow-hidden rounded-md border px-3 py-2.5 text-left transition-colors ${active ? "border-accent/55 bg-[linear-gradient(180deg,rgba(230,180,96,.16),rgba(230,180,96,.05))]" : state === "done" ? "border-line bg-[#171b21] hover:border-line-strong" : "border-line bg-card hover:border-line-strong"}`}
              >
                <span className="flex w-full items-center gap-2">
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
                <span className="max-w-full truncate text-[11.5px] text-muted">{STEPS[s].sub}</span>
                {(bar || active) && (
                  <span className={`absolute inset-x-0 bottom-0 h-[3px] ${active ? "bg-accent" : bar}`} />
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

/** 9:16 모니터: 첫 장면 이미지 위에 훅 자막과 Shorts UI 세이프존을 겹쳐 보여 준다 */
function Monitor({ project }: { project: Project }) {
  const hook = project.strategy?.scenes[0];
  const first = project.assets?.find((a) => a.image.path);
  const img = first ? fileUrl(project.id, first.image.path, project.version) : null;
  const doneCount = STEP_IDS.filter((s) => project.status[s] === "done").length;
  const total = project.timeline?.scenes.reduce((t, s) => t + (typeof s.duration === "number" ? s.duration : 0), 0);
  const length =
    project.render?.duration_sec || total || project.strategy?.scenes.at(-1)?.end || project.input?.duration_sec || 30;
  const fmt = (sec: number) => `00:${String(Math.round(sec)).padStart(2, "0")}`;
  return (
    <>
      <div className="relative mx-auto aspect-[9/16] w-full max-w-[236px] overflow-hidden rounded-2xl border border-line-strong bg-[radial-gradient(120%_80%_at_30%_15%,#3a3428_0%,#1b1a18_45%,#0c0d10_100%)] shadow-[0_30px_60px_-30px_rgba(0,0,0,.8)]">
        {img && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={img} alt="" className="absolute inset-0 h-full w-full object-cover opacity-80" />
        )}
        <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(0,0,0,.35)_0%,transparent_30%,transparent_55%,rgba(0,0,0,.6)_100%)]" />
        <div className="absolute top-[9%] right-[20%] bottom-[22%] left-[6%] rounded border border-dashed border-white/20" />
        <div className="absolute top-[5%] left-[8%] flex items-center gap-1.5 font-mono text-[9.5px] text-white/70">
          <span className="size-1.5 rounded-full bg-accent" />
          {hook ? `${hook.id} · ${hook.role.toUpperCase()}` : "PREVIEW"}
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
            전략을 만들면 훅 자막이 여기에 표시됩니다
          </div>
        )}
        <div className="absolute right-[8%] bottom-[7%] left-[8%]">
          <div className="h-[3px] rounded-full bg-white/20">
            <i
              className="block h-full rounded-full bg-white transition-[width] duration-700"
              style={{ width: `${(doneCount / 7) * 100}%` }}
            />
          </div>
          <div className="mt-1.5 flex justify-between font-mono text-[10px] text-white/60">
            <span>{project.render ? "완성" : `${doneCount}/7 단계`}</span>
            <span>{fmt(length)}</span>
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
  progress?: { stage: string; progress: number };
}
