import type { ButtonHTMLAttributes, ReactNode } from "react";
import { STATE_LABEL } from "@/lib/labels";
import type { StepState } from "@/lib/types";

type Variant = "primary" | "dark" | "ghost";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const base =
    "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-45";
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-white hover:bg-accent-strong",
    dark: "border border-ink bg-ink text-surface hover:bg-ink-2",
    ghost: "border border-line-strong bg-card text-ink hover:bg-surface",
  };
  return <button type="button" className={`${base} ${styles[variant]} ${className}`} {...props} />;
}

const STATE_STYLE: Record<StepState, string> = {
  idle: "bg-canvas text-muted border-line",
  running: "bg-accent-tint text-accent border-accent/30",
  done: "bg-ok-tint text-ok border-ok/25",
  stale: "bg-stale-tint text-stale-strong border-stale-line",
  error: "bg-err-tint text-err border-err/30",
};

export function StateBadge({ state }: { state: StepState }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap ${STATE_STYLE[state]}`}
    >
      {state === "running" && <span className="size-1.5 animate-pulse rounded-full bg-accent" />}
      {STATE_LABEL[state]}
    </span>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-[10px] border border-line bg-card p-4 ${className}`}>{children}</div>;
}

export function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`flex flex-col gap-1.5 ${wide ? "col-span-2" : ""}`}>
      <span className="text-[13px] font-medium text-ink-2">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  "min-h-11 rounded-lg border border-line-strong bg-card px-3 text-sm outline-none focus:border-accent";

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "error"; children: ReactNode }) {
  const style = {
    info: "border-accent/25 bg-accent-tint text-accent-strong",
    warn: "border-stale-line bg-stale-tint text-stale-strong",
    error: "border-err/30 bg-err-tint text-err",
  }[tone];
  return <div className={`rounded-lg border px-3 py-2 text-[13px] whitespace-pre-line ${style}`}>{children}</div>;
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-[12px] ${className}`}>{children}</span>;
}

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-line">
      <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}
