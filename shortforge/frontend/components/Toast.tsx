"use client";

import { useCallback, useState } from "react";

export interface ToastItem {
  id: number;
  tone: "ok" | "error" | "info";
  text: string;
  action?: { label: string; run: () => void };
}

let seq = 0;

/** 화면 오른쪽 아래 알림. 오류는 조금 더 오래 둔다. 한 번에 3개까지만 보인다 */
export function useToasts() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => setItems((t) => t.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (toast: Omit<ToastItem, "id">) => {
      const id = ++seq;
      setItems((t) => [...t.slice(-2), { ...toast, id }]);
      setTimeout(() => dismiss(id), toast.tone === "error" ? 8000 : 4000);
    },
    [dismiss],
  );
  return { items, push, dismiss };
}

const DOT: Record<ToastItem["tone"], string> = { ok: "bg-ok", error: "bg-err", info: "bg-accent" };

export function Toasts({ items, dismiss }: { items: ToastItem[]; dismiss: (id: number) => void }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-[min(360px,calc(100vw-32px))] flex-col gap-2"
    >
      {items.map((t) => (
        <div
          key={t.id}
          className="sf-toast pointer-events-auto flex items-center gap-3 rounded-[12px] border border-line-strong bg-card px-4 py-3 text-[13px] text-ink shadow-[0_18px_40px_-14px_rgba(0,0,0,.75)]"
        >
          <span className={`size-2 flex-none rounded-full ${DOT[t.tone]}`} aria-hidden="true" />
          <span className="min-w-0 flex-1">{t.text}</span>
          {t.action && (
            <button
              type="button"
              onClick={() => {
                t.action!.run();
                dismiss(t.id);
              }}
              className="flex-none text-[12.5px] font-semibold text-accent hover:text-accent-strong"
            >
              {t.action.label}
            </button>
          )}
          <button
            type="button"
            onClick={() => dismiss(t.id)}
            aria-label="알림 닫기"
            className="flex size-6 flex-none items-center justify-center rounded text-faint hover:bg-surface hover:text-ink"
          >
            <svg
              viewBox="0 0 16 16"
              width="11"
              height="11"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  );
}
