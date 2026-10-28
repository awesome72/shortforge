"use client";

import { useEffect } from "react";
import { Button } from "./ui";

/**
 * YouTube 영상을 크게 재생하는 창. 공식 플레이어(youtube-nocookie)로만 보여 주고 내려받지 않는다
 * (레퍼런스 영상 다운로드 금지 원칙).
 */
export function YouTubeModal({
  videoId,
  title,
  vertical = true,
  onClose,
  action,
}: {
  videoId: string;
  title: string;
  vertical?: boolean;
  onClose: () => void;
  action?: { label: string; run: () => void };
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div className="flex max-h-full flex-col items-center gap-4" onClick={(e) => e.stopPropagation()}>
        <iframe
          src={`https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0&playsinline=1`}
          title={title}
          allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
          allowFullScreen
          className={`rounded-2xl border border-line-strong bg-black ${
            vertical ? "aspect-[9/16] h-[min(78vh,760px)]" : "aspect-video w-[min(92vw,960px)]"
          }`}
        />
        <div className="flex w-full max-w-[520px] flex-wrap items-center justify-center gap-3">
          <p className="line-clamp-2 min-w-0 flex-1 text-[14px] text-white">{title}</p>
          {action && <Button onClick={action.run}>{action.label}</Button>}
          <Button variant="ghost" onClick={onClose}>
            닫기
          </Button>
        </div>
      </div>
    </div>
  );
}
