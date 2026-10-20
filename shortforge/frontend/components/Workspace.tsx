"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { FREE_TOOLS, STEPS, STATE_LABEL } from "@/lib/labels";
import { STEP_IDS, type AppConfig, type OutputKey, type Project, type StepId } from "@/lib/types";
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
import { Button, Notice, StateBadge } from "./ui";
import { VersionHistory } from "./VersionHistory";

const PROVIDER_LABEL: Record<string, string> = { anthropic: "Anthropic", openai: "OpenAI", openrouter: "OpenRouter" };

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
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-line bg-surface px-7 py-4">
        <div className="flex min-w-0 items-center gap-3.5">
          <Link
            href="/"
            className="flex size-[34px] flex-none items-center justify-center rounded-lg bg-ink font-display text-[13px] font-bold text-canvas no-underline hover:text-canvas"
          >
            SF
          </Link>
          <div className="min-w-0">
            <div className="font-display text-[16px] font-bold">ShortForge</div>
            <div className="truncate text-[12px] text-muted">
              {project.variant && (
                <span className="mr-1.5 rounded-full bg-accent-tint px-1.5 py-px font-medium text-accent-strong">
                  변형 {project.variant}
                </span>
              )}
              프로젝트 · {project.input?.topic ?? "(주제 없음)"} · 자동 저장됨 v{project.version}
              {project.parent_id && (
                <>
                  {" · "}
                  <Link href={`/p/${project.parent_id}`}>원본 보기</Link>
                </>
              )}
              {!connected && " · 실시간 연결 끊김"}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          {config?.advanced ? (
            <Link
              href="/settings"
              className="rounded-full border border-accent/30 bg-accent-tint px-3 py-1 text-[12px] font-medium text-accent-strong no-underline hover:text-accent-strong"
              title={`고급 모드(유료): ${config.advanced.tasks.join(", ")}만 ${config.advanced.model}로 처리. 나머지는 무료. UTC ${config.advanced.day_utc} 기준`}
            >
              고급 모드 · {PROVIDER_LABEL[config.advanced.provider] ?? config.advanced.provider}{" "}
              {config.advanced.label.split(" (")[0]} · 오늘 ${config.advanced.used_usd.toFixed(2)} / $
              {config.advanced.budget_usd.toFixed(2)}
            </Link>
          ) : (
            <span className="rounded-full border border-ok/25 bg-ok-tint px-3 py-1 text-[12px] font-medium text-ok">
              비용 ₩0 · 무료 스택
            </span>
          )}
          {quota?.images && (
            <span
              className="rounded-full border border-line bg-card px-3 py-1 font-mono text-[12px] text-ink-2"
              title={`Cloudflare Workers AI 무료 한도 (UTC ${quota.images.day_utc} 기준, 한국 오전 9시 초기화)`}
            >
              이미지 {quota.images.used.toLocaleString()} / {quota.images.limit.toLocaleString()} Neurons
            </span>
          )}
          {quota && (
            <span
              className={`rounded-full border px-3 py-1 font-mono text-[12px] ${quota.search_blocked ? "border-stale-line bg-stale-tint text-stale-strong" : "border-line bg-card text-ink-2"}`}
              title={`태평양 시간 ${quota.day_pt} 기준. 검색은 ${quota.search_limit} units에서 차단`}
            >
              YouTube 쿼터 {quota.used.toLocaleString()} / {quota.hard_limit.toLocaleString()}
            </span>
          )}
          <Button
            variant="dark"
            disabled={project.busy || !nextNeeded}
            onClick={() => nextNeeded && controls.runFrom(nextNeeded)}
            title={nextNeeded ? `${STEPS[nextNeeded].label}부터 끝까지` : "모든 단계 완료"}
          >
            {project.busy ? "실행 중…" : nextNeeded ? "전체 파이프라인 실행" : "모두 완료"}
          </Button>
        </div>
      </header>

      <SetupNotice config={config} />
      {config?.free_tier_notice && (
        <div className="border-b border-line bg-accent-tint px-7 py-2 text-[12px] text-accent-strong">
          무료 LLM 등급({config.llm_model}) 사용 중 — 입력 내용이 모델 개선에 쓰일 수 있고 상업적 이용이 제외된다.
          민감한 내용은 로컬 모드(LLM_MODE=ollama)로 실행한다.
        </div>
      )}
      {config?.llm_mode === "fake" && (
        <div className="border-b border-stale-line bg-stale-tint px-7 py-2 text-[12px] text-stale-strong">
          개발 모드: LLM이 Fake다 (DEV_FAKE_LLM). 키워드·요인·전략은 고정 예시로 채워진다.
        </div>
      )}
      {error && (
        <div className="px-7 pt-3">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      <div className="flex flex-1 flex-wrap">
        <nav className="min-w-0 flex-[1_1_248px] border-r border-line bg-surface px-4 py-6 lg:max-w-[300px]">
          <div className="mb-3 px-2 font-mono text-[11px] tracking-wider text-muted">파이프라인</div>
          <div className="flex flex-col gap-1">
            {STEP_IDS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setTab(s)}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors ${tab === s ? "bg-card shadow-[inset_0_0_0_1px_var(--color-line-strong)]" : "hover:bg-card/60"}`}
              >
                <span
                  className={`flex size-7 flex-none items-center justify-center rounded-md font-mono text-[12px] ${tab === s ? "bg-ink text-canvas" : "bg-canvas text-ink-2"}`}
                >
                  {STEPS[s].n}
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="text-[14px] font-medium">{STEPS[s].label}</span>
                  <span className="truncate text-[12px] text-muted">{STEPS[s].sub}</span>
                </span>
                <StateBadge state={project.status[s]} />
              </button>
            ))}
          </div>
          <p className="mt-5 px-2 text-[12px] leading-relaxed text-muted">
            각 탭은 같은 Project JSON을 읽고 씁니다. 앞 단계를 고치면 뒤 단계에 &quot;재생성 필요&quot; 표시가
            붙습니다.
          </p>
        </nav>

        <main className="min-w-0 flex-[999_1_560px] p-7">
          {tab === "s1" && <S1Input {...common} progress={progress.s1} />}
          {tab === "s2" && <S2Refs {...common} progress={progress.s2} />}
          {tab === "s3" && <S3Factors {...common} progress={progress.s3} />}
          {tab === "s4" && <S4Strategy {...common} progress={progress.s4} />}
          {tab === "s5" && <S5Assets {...common} progress={progress.s5} />}
          {tab === "s6" && <S6Timeline {...common} progress={progress.s6} />}
          {tab === "s7" && <S7Render {...common} progress={progress.s7} />}
        </main>

        <aside className="min-w-0 flex-[1_1_280px] border-l border-line bg-surface px-5 py-6 xl:max-w-[340px]">
          <div className="mb-3 font-mono text-[11px] tracking-wider text-muted">PROJECT JSON · 탭 간 연결</div>
          <div className="flex flex-col gap-1">
            {STEP_IDS.map((s) => {
              const key = KEY_OF[s];
              const value = project[key];
              return (
                <div key={s}>
                  <button
                    type="button"
                    onClick={() => setOpenKey(openKey === key ? null : key)}
                    className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left hover:bg-card"
                  >
                    <span className="font-mono text-[13px]">
                      {key}
                      {Array.isArray(value) ? `[${value.length}]` : ""}
                    </span>
                    <span className="text-[12px] text-muted" title={STATE_LABEL[project.status[s]]}>
                      <StateBadge state={project.status[s]} />
                    </span>
                  </button>
                  {openKey === key && (
                    <pre className="mx-2 mb-2 max-h-72 overflow-auto rounded-md border border-line bg-card p-2 font-mono text-[11px] leading-snug">
                      {value ? JSON.stringify(value, null, 2) : "null"}
                    </pre>
                  )}
                </div>
              );
            })}
          </div>

          <div className="mt-7 mb-2 font-mono text-[11px] tracking-wider text-muted">버전 기록</div>
          <VersionHistory key={project.id} project={project} guard={guard} />

          <div className="mt-7 mb-2 font-mono text-[11px] tracking-wider text-muted">관리</div>
          <ProjectTools project={project} guard={guard} />

          <div className="mt-7 mb-3 font-mono text-[11px] tracking-wider text-muted">이 단계의 무료 도구</div>
          <div className="flex flex-col gap-2">
            {FREE_TOOLS[tab].map((t) => (
              <div key={t.name} className="rounded-lg border border-line bg-card p-3">
                <div className="text-[13px] font-semibold">{t.name}</div>
                <div className="text-[12px] text-ink-2">{t.limit}</div>
                <div className="mt-1 text-[12px] text-stale">주의: {t.risk}</div>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
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
