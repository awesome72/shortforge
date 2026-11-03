"use client";

import { useState } from "react";
import { api } from "@/lib/api";

/** 실행 중인 작업 멈추기. 이전 결과는 그대로 두고, 다시 시도하면 그 단계부터 이어서 만든다 */
export function StopButton({ id, className = "" }: { id: string; className?: string }) {
  const [state, setState] = useState<"idle" | "stopping" | "cannot">("idle");
  return (
    <button
      type="button"
      disabled={state === "stopping"}
      title={state === "cannot" ? "여러 영상을 한 번에 다시 만드는 중이라 이 화면에서는 멈출 수 없어요" : undefined}
      onClick={() => {
        setState("stopping");
        api
          .cancelRun(id)
          .then((r) => {
            if (r.cancelled) return; // 화면이 곧 멈춘 상태로 바뀐다
            setState("cannot"); // 일괄 다시 렌더처럼 이 버튼으로 멈출 수 없는 작업
            window.setTimeout(() => setState("idle"), 4000);
          })
          .catch(() => setState("idle"));
      }}
      className={`text-[13px] font-normal text-muted hover:text-ink disabled:opacity-50 ${className}`}
    >
      {state === "stopping" ? "멈추는 중…" : state === "cannot" ? "지금은 멈출 수 없어요" : "멈추기"}
    </button>
  );
}
