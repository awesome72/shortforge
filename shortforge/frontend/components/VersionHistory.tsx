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
      <button type="button" className="px-2 text-[13px] text-accent hover:underline" onClick={load}>
        버전 기록 보기
      </button>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      {items.map((v) => {
        const done = STEP_IDS.filter((s) => v.status[s] === "done").length;
        const current = v.version === project.version;
        return (
          <div
            key={v.version}
            className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-[12px] hover:bg-card"
          >
            <div className="min-w-0">
              <div className="font-mono">
                v{v.version} · {new Date(v.updated_at).toLocaleString("ko-KR", { hour12: false })}
              </div>
              <div className="truncate text-muted" title={v.title ?? ""}>
                {done}/7 완료{v.has_render ? " · 영상 있음" : ""}
                {v.title ? ` · ${v.title}` : ""}
              </div>
            </div>
            {current ? (
              <span className="flex-none text-muted">현재</span>
            ) : (
              <button
                type="button"
                disabled={project.busy}
                onClick={() => restore(v.version)}
                className={`flex-none rounded px-2 py-0.5 ${armed === v.version ? "bg-stale text-white" : "text-accent hover:underline"} disabled:opacity-40`}
              >
                {armed === v.version ? "한 번 더 눌러 되돌리기" : "되돌리기"}
              </button>
            )}
          </div>
        );
      })}
      <p className="px-2 pt-1 text-[11px] leading-relaxed text-muted">
        되돌리면 새 버전으로 저장된다. 5~7단계는 파일이 바뀌었을 수 있어 &quot;재생성 필요&quot;가 된다.
      </p>
    </div>
  );
}
