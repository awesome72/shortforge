import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { STATE_LABEL } from "@/lib/labels";
import type { StepState } from "@/lib/types";

type Variant = "primary" | "dark" | "ghost" | "quiet";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const base =
    "inline-flex min-h-10 items-center justify-center gap-2 whitespace-nowrap rounded-[10px] px-4 text-[13.5px] font-semibold tracking-[-0.005em] transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-40";
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-accent-ink hover:bg-accent-strong",
    // 예전 "진한" 버튼: 어두운 화면에서는 텅스텐 주 버튼과 같은 역할
    dark: "bg-accent text-accent-ink hover:bg-accent-strong",
    ghost: "border border-line-strong text-ink hover:border-muted hover:bg-card",
    quiet: "text-ink-2 hover:bg-card hover:text-ink",
  };
  return <button type="button" className={`${base} ${styles[variant]} ${className}`} {...props} />;
}

const STATE_STYLE: Record<StepState, string> = {
  idle: "text-muted shadow-[inset_0_0_0_1px_var(--color-line-strong)]",
  running: "bg-accent-tint text-accent",
  done: "bg-ok-tint text-ok",
  stale: "text-stale shadow-[inset_0_0_0_1px_var(--color-stale-line)]",
  error: "bg-err-tint text-err",
};

export function StateBadge({ state }: { state: StepState }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap ${STATE_STYLE[state]}`}
    >
      <span
        className={`size-1.5 rounded-full ${state === "idle" ? "border border-dashed border-current" : "bg-current"} ${state === "running" ? "sf-pulse" : ""}`}
      />
      {STATE_LABEL[state]}
    </span>
  );
}

/** 패널: 편집실 화면의 기본 면 (둥근 14px, 한 단 밝은 배경) */
export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-[14px] border border-line bg-surface p-[18px] ${className}`}>{children}</div>;
}

/** 머리글이 있는 패널 (제목 + 오른쪽 보조 문구) */
export function Panel({
  title,
  aside,
  children,
  className = "",
  bodyClassName = "p-[18px]",
}: {
  title: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`overflow-hidden rounded-[14px] border border-line bg-surface ${className}`}>
      <div className="flex items-center justify-between gap-3 border-b border-line px-[18px] py-3.5">
        <h3 className="text-[13.5px] font-semibold">{title}</h3>
        {aside && <span className="text-[12px] text-muted">{aside}</span>}
      </div>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`flex min-w-0 flex-col gap-[7px] ${wide ? "col-span-2" : ""}`}>
      <span className="text-[12.5px] font-medium text-ink-2">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  "min-h-11 rounded-[10px] border border-line-strong bg-sunken px-3.5 text-sm text-ink outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-muted-2 focus:border-accent focus:shadow-[0_0_0_3px_var(--color-accent-tint)]";

const NOTICE_STYLE = {
  info: "border-line bg-card text-ink-2",
  warn: "border-stale-line bg-stale-tint text-stale-strong",
  error: "border-err/30 bg-err-tint text-err",
};

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "error"; children: ReactNode }) {
  return (
    <div className={`rounded-[10px] border px-4 py-3 text-[13px] whitespace-pre-line ${NOTICE_STYLE[tone]}`}>
      {children}
    </div>
  );
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-[12px] ${className}`}>{children}</span>;
}

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-[3px] w-full overflow-hidden rounded-full bg-line">
      <div
        className="h-full rounded-full bg-accent transition-[width] duration-500"
        style={{ width: `${Math.round(value * 100)}%` }}
      />
    </div>
  );
}

/** 상단 바 왼쪽의 브랜드 (홈으로 가는 링크) */
export function Brand() {
  return (
    <Link href="/" className="flex min-w-0 items-center gap-3 text-ink no-underline hover:text-ink">
      <span className="sf-mark" aria-hidden="true" />
      <span className="text-[16px] font-bold tracking-[-0.02em]">ShortForge</span>
    </Link>
  );
}

/** 작은 막대 미터 (쿼터·한도) */
export function Meter({
  label,
  used,
  limit,
  warn = false,
  title,
}: {
  label: string;
  used: number;
  limit: number;
  warn?: boolean;
  title?: string;
}) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  return (
    <div className="flex min-w-[168px] flex-col gap-[5px]" title={title}>
      <div className="flex justify-between gap-3 text-[11.5px] whitespace-nowrap text-muted">
        <span>{label}</span>
        <b className={`font-mono font-medium ${warn ? "text-stale" : "text-ink-2"}`}>
          {used.toLocaleString()} / {limit.toLocaleString()}
        </b>
      </div>
      <div className="h-[3px] rounded-full bg-line">
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${warn ? "bg-stale" : "bg-ink-2"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/** 세그먼트 선택 (톤·길이·엔진처럼 2~4개 중 하나) */
export function Seg<T extends string | number>({
  options,
  value,
  onChange,
  disabled = false,
  label,
}: {
  options: { value: T; label: ReactNode; disabled?: boolean; title?: string }[];
  value: T;
  onChange: (v: T) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="flex min-h-11 rounded-[10px] border border-line-strong bg-sunken p-[3px]"
    >
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          aria-pressed={o.value === value}
          disabled={disabled || o.disabled}
          title={o.title}
          onClick={() => onChange(o.value)}
          className="flex-1 rounded-[7px] px-2 text-[13px] whitespace-nowrap text-muted transition-colors hover:text-ink-2 disabled:cursor-not-allowed disabled:opacity-40 aria-pressed:bg-card aria-pressed:text-ink aria-pressed:shadow-[inset_0_0_0_1px_var(--color-line-strong)]"
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
