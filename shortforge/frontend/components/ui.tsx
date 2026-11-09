import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";

type Variant = "primary" | "dark" | "ghost" | "quiet";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; ref?: Ref<HTMLButtonElement> }) {
  const base =
    "inline-flex min-h-10 items-center justify-center gap-2 whitespace-nowrap rounded-ctl px-4 text-sm font-semibold tracking-[-0.005em] transition-colors duration-150 disabled:cursor-not-allowed";
  // 주 버튼이 비활성이면 흐린 앰버(탁한 갈색으로 보인다) 대신 중립 면으로 바꾼다
  const solid =
    "bg-accent text-accent-ink enabled:hover:bg-accent-strong disabled:bg-card disabled:text-faint disabled:shadow-[inset_0_0_0_1px_var(--color-line)]";
  const styles: Record<Variant, string> = {
    primary: solid,
    // 예전 "진한" 버튼: 어두운 화면에서는 텅스텐 주 버튼과 같은 역할
    dark: solid,
    ghost:
      "border border-line-strong text-ink enabled:hover:border-muted enabled:hover:bg-card disabled:text-faint disabled:border-line",
    quiet: "text-ink-2 enabled:hover:bg-card enabled:hover:text-ink disabled:text-faint",
  };
  return <button type="button" className={`${base} ${styles[variant]} ${className}`} {...props} />;
}

/** 패널: 편집실 화면의 기본 면 (둥근 14px, 한 단 밝은 배경) */
export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-panel bg-surface shadow-panel p-[18px] ${className}`}>{children}</div>;
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
    <section className={`overflow-hidden rounded-panel bg-surface shadow-panel ${className}`}>
      <div className="flex items-center justify-between gap-3 border-b border-line px-[18px] py-3.5">
        <h3 className="text-sm font-semibold">{title}</h3>
        {aside && <span className="text-xs text-muted">{aside}</span>}
      </div>
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`flex min-w-0 flex-col gap-[7px] ${wide ? "col-span-2" : ""}`}>
      <span className="text-xs font-medium text-ink-2">{label}</span>
      {children}
    </label>
  );
}

/** 누르면 바로 저장되는 켜기·끄기 (체크박스 대신 스위치 모양: 바로 바뀐다는 것을 모양으로 알린다) */
export const switchClass =
  "relative mt-0.5 h-[22px] w-[38px] flex-none cursor-pointer appearance-none rounded-full bg-card shadow-[inset_0_0_0_1px_var(--color-line-strong)] transition-colors before:absolute before:top-[3px] before:left-[3px] before:size-4 before:rounded-full before:bg-muted before:transition-transform checked:bg-accent checked:shadow-none checked:before:translate-x-4 checked:before:bg-accent-ink disabled:cursor-not-allowed disabled:opacity-50";

export const inputClass =
  "min-h-11 rounded-ctl border border-line-strong bg-sunken px-3.5 text-md text-ink outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-muted-2 focus:border-accent focus:shadow-[0_0_0_3px_var(--color-accent-tint)]";

const NOTICE_STYLE = {
  info: "border-line bg-card text-ink-2",
  warn: "border-stale-line bg-stale-tint text-stale-strong",
  error: "border-err/30 bg-err-tint text-err",
};

export function Notice({
  tone = "info",
  live = true,
  children,
}: {
  tone?: "info" | "warn" | "error";
  live?: boolean; // 버튼·입력란이 든 상자는 false로 두고 안내 문구에만 역할을 단다(상자 전체가 다시 읽혔다)
  children: ReactNode;
}) {
  return (
    <div
      role={live ? (tone === "error" ? "alert" : "status") : undefined}
      className={`rounded-ctl border px-4 py-3 text-sm whitespace-pre-line ${NOTICE_STYLE[tone]}`}
    >
      {children}
    </div>
  );
}

/** 기술 설명은 접어 두고 필요할 때 펼친다 */
export function Details({
  children,
  summary = "자세히",
  className = "",
}: {
  children: ReactNode;
  summary?: ReactNode;
  className?: string;
}) {
  return (
    <details className={`group ${className}`}>
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs text-muted select-none hover:text-ink-2 [&::-webkit-details-marker]:hidden">
        <svg
          viewBox="0 0 16 16"
          width="12"
          height="12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="transition-transform group-open:rotate-90"
          aria-hidden="true"
        >
          <path d="M6 3.5L10.5 8 6 12.5" />
        </svg>
        {summary}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-xs ${className}`}>{children}</span>;
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
      <span className="text-lg font-bold tracking-[-0.02em]">ShortForge</span>
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
      <div className="flex justify-between gap-3 text-2xs whitespace-nowrap text-muted">
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
      className="flex min-h-11 rounded-ctl border border-line-strong bg-sunken p-[3px]"
    >
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          aria-pressed={o.value === value}
          disabled={disabled || o.disabled}
          title={o.title}
          onClick={() => onChange(o.value)}
          className="flex-1 rounded-md px-2 text-sm whitespace-nowrap text-muted transition-colors hover:text-ink-2 disabled:cursor-not-allowed disabled:opacity-40 aria-pressed:bg-card aria-pressed:text-ink aria-pressed:shadow-[inset_0_0_0_1px_var(--color-line-strong)]"
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
