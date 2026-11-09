import Link from "next/link";
import type { ReactNode } from "react";
import { ThemeToggle } from "./ThemeToggle";
import { Brand } from "./ui";

/** 홈·설정 화면의 상단 바 (작업 화면은 Workspace가 자체 상단 바를 그린다) */
export function AppBar({ crumb, right }: { crumb?: ReactNode; right?: ReactNode }) {
  return (
    <header className="sticky top-0 z-20 flex h-[60px] items-center gap-5 border-b border-line bg-surface px-6">
      <Brand />
      {crumb && (
        <div className="hidden min-w-0 items-center gap-2 text-sm text-muted sm:flex">
          <span className="text-faint">/</span>
          <b className="truncate font-medium text-ink-2">{crumb}</b>
        </div>
      )}
      <div className="ml-auto flex items-center gap-3">
        <ThemeToggle />
        {right ?? (
          <>
            <span className="hidden rounded-full bg-ok-tint px-2.5 py-[5px] text-xs text-ok sm:inline">
              비용 ₩0 · 무료 스택
            </span>
            <Link
              href="/settings"
              className="inline-flex min-h-9 items-center rounded-ctl border border-line-strong px-3.5 text-sm font-semibold text-ink no-underline hover:border-muted hover:bg-card hover:text-ink"
            >
              설정
            </Link>
          </>
        )}
      </div>
    </header>
  );
}
