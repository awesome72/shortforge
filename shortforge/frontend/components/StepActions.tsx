"use client";

import { STEPS } from "@/lib/labels";
import type { Project, StepId } from "@/lib/types";
import type { StepProgress } from "@/lib/useProject";
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
  const disabled = project.busy || blockers.length > 0;
  const running = project.status[step] === "running";
  const warnings = project.warnings[step] ?? [];
  const error = project.errors[step];

  return (
    <div className="mt-6 flex flex-col gap-3">
      {running && progress && (
        <div className="flex flex-col gap-1">
          <div className="flex justify-between text-[12px] text-muted">
            <span className="font-mono">{progress.stage}</span>
            <span>{Math.round(progress.progress * 100)}%</span>
          </div>
          <ProgressBar value={progress.progress} />
        </div>
      )}
      {error && <Notice tone="error">{error}</Notice>}
      {warnings.length > 0 && (
        <Notice tone="warn">
          {warnings.map((w) => (
            <div key={w}>· {w}</div>
          ))}
        </Notice>
      )}
      <div className="flex flex-wrap items-center gap-2.5">
        <Button disabled={disabled} onClick={async () => (await beforeRun?.(), controls.run(step))}>
          {running ? "실행 중…" : primaryLabel}
        </Button>
        {next && (
          <Button
            variant="ghost"
            disabled={disabled}
            onClick={async () => (await beforeRun?.(), controls.runFrom(step))}
          >
            여기서부터 끝까지 실행
          </Button>
        )}
        {blockers.length > 0 && (
          <span className="text-[13px] text-muted">
            먼저 {blockers.map((b) => `${STEPS[b].n}. ${STEPS[b].label}`).join(", ")}을(를) 완료해야 한다
          </span>
        )}
      </div>
    </div>
  );
}

export function StepHeader({ step, title, desc }: { step: StepId; title: string; desc: string }) {
  return (
    <header className="mb-5">
      <div className="font-mono text-[12px] tracking-wide text-accent">
        STEP {STEPS[step].n} · {STEPS[step].label}
      </div>
      <h1 className="mt-1 font-display text-[26px] font-bold tracking-tight">{title}</h1>
      <p className="mt-1 max-w-3xl text-muted">{desc}</p>
    </header>
  );
}
