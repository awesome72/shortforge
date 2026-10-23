"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { STEP_IDS, type Project, type VersionSummary } from "@/lib/types";

/** 버전 기록과 되돌리기 (F-W5). 되돌림도 새 버전으로 저장되므로 다시 되돌릴 수 있다. */
export function VersionHistory({
  project,
  guard,
}: {
  project: Project;
  guard: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [items, setItems] = useState<VersionSummary[] | null>(null);
  const [armed, setArmed] = useState<number | null>(null); // 브라우저 확인창 대신 두 번 눌러 확인

  const load = () => guard(async () => setItems(await api.versions(project.id)));
  const restore = (v: number) =>
    guard(async () => {
      if (armed !== v) {
        setArmed(v);
        return;
      }
      setArmed(null);
      await api.restoreVersion(project.id, v); // 화면은 SSE(edited)로 갱신된다
      setItems(await api.versions(project.id));
    });

  if (items === null) {
    return (
      <button
        type="button"
        className="w-full rounded-[10px] border border-dashed border-line-strong px-3 py-2.5 text-left text-[13px] text-ink-2 hover:border-muted hover:text-ink"
        onClick={load}
      >
        버전 기록 보기
      </button>
    );
  }
  return (
    <div className="overflow-hidden rounded-[10px] border border-line bg-surface">
      <div className="max-h-[320px] overflow-y-auto">
        {items.map((v) => {
          const done = STEP_IDS.filter((s) => v.status[s] === "done").length;
          const current = v.version === project.version;
          return (
            <div
              key={v.version}
              className={`flex items-center justify-between gap-2 border-b border-line px-3 py-2.5 text-[12px] last:border-0 ${current ? "bg-accent-tint" : "hover:bg-card"}`}
            >
              <div className="min-w-0">
                <div className="font-mono text-ink-2">
                  <b className={current ? "text-accent" : "text-ink"}>v{v.version}</b> ·{" "}
                  {new Date(v.updated_at).toLocaleString("ko-KR", {
                    month: "numeric",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: false,
                  })}
                </div>
                <div className="truncate text-muted" title={v.title ?? ""}>
                  {done}/7 완료{v.has_render ? " · 영상 있음" : ""}
                  {v.title ? ` · ${v.title}` : ""}
                </div>
              </div>
              {current ? (
                <span className="flex-none text-[11.5px] font-medium text-accent">현재</span>
              ) : (
                <button
                  type="button"
                  disabled={project.busy}
                  onClick={() => restore(v.version)}
                  className={`flex-none rounded px-2 py-0.5 ${armed === v.version ? "bg-stale font-semibold text-canvas" : "text-ink-2 hover:bg-line hover:text-ink"} disabled:opacity-40`}
                >
                  {armed === v.version ? "한 번 더 눌러 되돌리기" : "되돌리기"}
                </button>
              )}
            </div>
          );
        })}
      </div>
      <p className="border-t border-line px-3 py-2.5 text-[11px] leading-relaxed text-faint">
        되돌리면 새 버전으로 저장된다. 5~7단계는 파일이 바뀌었을 수 있어 &quot;재생성 필요&quot;가 된다.
      </p>
    </div>
  );
}
