"use client";

import { STEPS } from "@/lib/labels";
import type { AdvancedInfo, Project, StepId } from "@/lib/types";
import type { StepProgress } from "@/lib/useProject";
import type { ReactNode } from "react";
import { Button, Details, Notice, ProgressBar } from "./ui";

// 고급 모드(D13) 작업 이름 → 그 작업을 하는 단계
const ADVANCED_TASK_STEP: Record<string, StepId> = { s3_factors: "s3", s4_strategy: "s4" };

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
  advanced,
}: {
  project: Project;
  step: StepId;
  controls: RunControls;
  progress?: StepProgress;
  primaryLabel: string;
  next?: StepId;
  /** 실행 전에 할 일 (예: 저장하지 않은 편집 저장) */
  beforeRun?: () => Promise<void>;
  /** 고급 모드(유료) 정보: 이 단계가 유료 모델로 처리되면 버튼 옆에 미리 알린다 */
  advanced?: AdvancedInfo | null;
}) {
  const blockers = project.blockers[step];
  const notReady = project.not_ready?.[step];
  const disabled = project.busy || blockers.length > 0 || !!notReady;
  const usage = project.llm_usage?.[step];
  const paid = usage?.providers.some((p) => p !== "gemini" && p !== "ollama");
  const running = project.status[step] === "running";
  const warnings = project.warnings[step] ?? [];
  const error = project.errors[step];
  const paidAhead = !!advanced?.tasks.some((t) => ADVANCED_TASK_STEP[t] === step);

  return (
    <div className="mt-7 flex flex-col gap-3">
      {running && progress && (
        <div className="flex flex-col gap-1.5 rounded-[10px] border border-line bg-surface px-4 py-3">
          <div className="flex justify-between text-[12px] text-muted">
            <span className="flex items-center gap-2 text-accent">
              <span className="sf-pulse size-1.5 rounded-full bg-accent" />
              {progress.stage}
            </span>
            <span className="tabular-nums">{Math.round(progress.progress * 100)}%</span>
          </div>
          <ProgressBar value={progress.progress} />
        </div>
      )}
      {notReady && (
        <Notice tone="warn">
          <div className="font-semibold">아직 실행할 수 없어요</div>
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
        {paidAhead && !running && (
          <span
            className="rounded-full bg-accent-tint px-2.5 py-[3px] text-[12px] text-accent tabular-nums"
            title="설정에서 고급 모드를 끄면 무료 경로로 처리해요"
          >
            실행하면 유료 모델({advanced!.model}) · 오늘 ${advanced!.used_usd.toFixed(2)} / $
            {advanced!.budget_usd.toFixed(2)}
          </span>
        )}
        {usage && project.status[step] !== "running" && (
          <span
            className={`text-[12px] tabular-nums ${paid ? "text-accent" : "text-muted"}`}
            title={`LLM 요청 ${usage.calls}회`}
          >
            처리: {usage.models.join(", ")}
            {paid ? ` · 고급 모드 $${usage.usd.toFixed(4)}` : " · 무료"}
          </span>
        )}
        {blockers.length > 0 && (
          <span className="text-[12.5px] text-muted">
            {blockers.map((b) => `${STEPS[b].n}. ${STEPS[b].label}`).join(", ")}을(를) 먼저 마쳐 주세요
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
        <Button
          data-run-primary
          disabled={disabled}
          title="Ctrl+Enter"
          onClick={async () => (await beforeRun?.(), controls.run(step))}
        >
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
  tech,
  right,
}: {
  step: StepId;
  title: string;
  desc: string;
  /** 동작 방식처럼 궁금한 사람만 볼 설명 ("자세히"로 접어 둔다) */
  tech?: ReactNode;
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
        <h1 className="text-[28px] leading-[1.18] font-bold tracking-[-0.03em] text-balance">{title}</h1>
        <p className="mt-2.5 max-w-[54ch] text-[15px] leading-[1.65] text-pretty text-ink-2">{desc}</p>
        {tech && (
          <Details className="mt-2">
            <div className="max-w-[68ch] text-[13px] leading-relaxed text-muted">{tech}</div>
          </Details>
        )}
      </div>
      {right}
    </header>
  );
}
