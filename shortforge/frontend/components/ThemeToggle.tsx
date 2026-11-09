"use client";

import { useSyncExternalStore } from "react";
import { Icon, type IconName } from "./Icon";

/** 화면 밝기: 어둡게(기본) · 밝게 · 시스템 따라. 이 브라우저에만 기억한다 (layout.tsx가 그리기 전에 읽는다) */
export type Theme = "dark" | "light" | "system";

const KEY = "sf-theme";
export const THEME_LABEL: Record<Theme, string> = { dark: "어둡게", light: "밝게", system: "시스템 따라" };
const ICON: Record<Theme, IconName> = { dark: "moon", light: "sun", system: "monitor" };
const NEXT: Record<Theme, Theme> = { dark: "light", light: "system", system: "dark" };

export function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t;
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* 저장소를 쓸 수 없으면 이번 화면에만 적용한다 */
  }
  window.dispatchEvent(new Event("sf-theme"));
}

/** 지금 테마 (다른 곳에서 바꿔도 따라간다. 서버 렌더에서는 기본값) */
export function useTheme(): Theme {
  return useSyncExternalStore(
    (cb) => {
      window.addEventListener("sf-theme", cb);
      return () => window.removeEventListener("sf-theme", cb);
    },
    () => (document.documentElement.dataset.theme as Theme) || "dark",
    () => "dark",
  );
}

/** 상단 바의 작은 버튼: 누를 때마다 어둡게 → 밝게 → 시스템 따라 */
export function ThemeToggle({ className = "", small = false }: { className?: string; small?: boolean }) {
  const theme = useTheme();
  return (
    <button
      type="button"
      onClick={() => applyTheme(NEXT[theme])}
      aria-label={`화면 밝기: ${THEME_LABEL[theme]} (누르면 ${THEME_LABEL[NEXT[theme]]})`}
      title={`화면 밝기: ${THEME_LABEL[theme]}`}
      className={`grid ${small ? "size-7" : "size-9"} place-items-center rounded-ctl text-muted hover:bg-card hover:text-ink ${className}`}
    >
      <Icon name={ICON[theme]} />
    </button>
  );
}
