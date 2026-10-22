"use client";

import { STEPS } from "@/lib/labels";
import type { Project, StepId } from "@/lib/types";
import type { StepProgress } from "@/lib/useProject";
import type { ReactNode } from "react";
import { Button, Notice, ProgressBar } from "./ui";

export interface RunControls {
  run: (step: StepId) => Promise<void>;
  runFrom: (step: StepId) => Promise<void>;
}

/** 단계 공통: 실행 버튼, 막힘 사유, 진행률, 경고·오류. */
export function StepActions({
  project,
  step,
  controls,
  progress,
  primaryLabel,
  next,
  beforeRun,
}: {
  project: Project;
  step: StepId;
  controls: RunControls;
  progress?: StepProgress;
  primaryLabel: string;
  next?: StepId;
  /** 실행 전에 할 일 (예: 저장하지 않은 편집 저장) */
  beforeRun?: () => Promise<void>;
}) {
  const blockers = project.blockers[step];
  const notReady = project.not_ready?.[step];
  const disabled = project.busy || blockers.length > 0 || !!notReady;
  const usage = project.llm_usage?.[step];
  const paid = usage?.providers.some((p) => p !== "gemini" && p !== "ollama");
  const running = project.status[step] === "running";
  const warnings = project.warnings[step] ?? [];
  const error = project.errors[step];

  return (
    <div className="mt-7 flex flex-col gap-3">
      {running && progress && (
        <div className="flex flex-col gap-1.5 rounded-[10px] border border-line bg-surface px-4 py-3">
          <div className="flex justify-between text-[12px] text-muted">
            <span className="flex items-center gap-2 font-mono text-accent">
              <span className="sf-pulse size-1.5 rounded-full bg-accent" />
              {progress.stage}
            </span>
            <span className="font-mono">{Math.round(progress.progress * 100)}%</span>
          </div>
          <ProgressBar value={progress.progress} />
        </div>
      )}
      {notReady && (
        <Notice tone="warn">
          <div className="font-semibold">아직 실행할 수 없다</div>
          <div>{notReady}</div>
        </Notice>
      )}
      {error && !notReady && <Notice tone="error">{error}</Notice>}
      {warnings.length > 0 && (
        <Notice tone="warn">
          {warnings.map((w) => (
            <div key={w}>· {w}</div>
          ))}
        </Notice>
      )}
      <div className="flex flex-wrap items-center gap-2.5 border-t border-line pt-5">
        {usage && project.status[step] !== "running" && (
          <span
            className={`font-mono text-[11.5px] ${paid ? "text-accent" : "text-muted"}`}
            title={`LLM 요청 ${usage.calls}회`}
          >
            처리: {usage.models.join(", ")}
            {paid ? ` · 고급 모드 $${usage.usd.toFixed(4)}` : " · 무료"}
          </span>
        )}
        {blockers.length > 0 && (
          <span className="text-[12.5px] text-muted">
            먼저 {blockers.map((b) => `${STEPS[b].n}. ${STEPS[b].label}`).join(", ")}을(를) 완료해야 한다
          </span>
        )}
        <span className="flex-1" />
        {next && (
          <Button
            variant="ghost"
            disabled={disabled}
            onClick={async () => (await beforeRun?.(), controls.runFrom(step))}
          >
            여기서부터 끝까지 실행
          </Button>
        )}
        <Button disabled={disabled} onClick={async () => (await beforeRun?.(), controls.run(step))}>
          {running ? (
            <>
              <span className="sf-pulse size-1.5 rounded-full bg-accent-ink" />
              실행 중…
            </>
          ) : (
            <>
              <PlayIcon />
              {primaryLabel}
            </>
          )}
        </Button>
      </div>
    </div>
  );
}

function PlayIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
      <path d="M4 2.8v10.4a.6.6 0 0 0 .9.5l8.3-5.2a.6.6 0 0 0 0-1L4.9 2.3a.6.6 0 0 0-.9.5z" />
    </svg>
  );
}

export function StepHeader({
  step,
  title,
  desc,
  right,
}: {
  step: StepId;
  title: string;
  desc: string;
  right?: ReactNode;
}) {
  return (
    <header className="mb-[26px] flex flex-wrap items-end justify-between gap-6">
      <div className="min-w-0">
        <div className="mb-2.5 flex items-center gap-2.5 text-[12.5px] text-muted">
          <span className="rounded bg-accent-tint px-[7px] py-0.5 font-mono text-[12px] text-accent">
            STEP {String(STEPS[step].n).padStart(2, "0")}
          </span>
          <span>{STEPS[step].label}</span>
        </div>
        <h1 className="text-[30px] leading-[1.2] font-bold tracking-[-0.035em]">{title}</h1>
        <p className="mt-2 max-w-[62ch] text-[14.5px] text-ink-2">{desc}</p>
      </div>
      {right}
    </header>
  );
}
