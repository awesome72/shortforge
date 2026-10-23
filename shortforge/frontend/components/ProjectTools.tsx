"use client";

import { useState } from "react";
import { api, supportBundleUrl } from "@/lib/api";
import type { Project } from "@/lib/types";

/** 오른쪽 패널의 관리 도구: 안 쓰는 파일 정리, 문제 보고용 파일 받기 */
export function ProjectTools({
  project,
  guard,
}: {
  project: Project;
  guard: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [result, setResult] = useState<string | null>(null);
  const cleanup = () =>
    guard(async () => {
      const r = await api.cleanup(project.id);
      setResult(
        r.removed
          ? `파일 ${r.removed}개, ${(r.freed_bytes / 1_048_576).toFixed(1)}MB를 지웠어요`
          : "지울 파일이 없어요",
      );
    });

  return (
    <div className="flex flex-col gap-2 text-[13px]">
      <button
        type="button"
        className="flex items-center justify-between rounded-[10px] border border-line bg-surface px-3 py-2.5 text-left text-ink-2 hover:border-line-strong hover:text-ink disabled:cursor-not-allowed disabled:text-faint"
        disabled={project.busy}
        onClick={cleanup}
        title="고르지 않은 후보, 다시 만들기 전 이미지처럼 어떤 버전에서도 쓰지 않는 파일을 지워요"
      >
        안 쓰는 파일 정리 <span className="font-mono text-[11px] text-faint">cleanup</span>
      </button>
      {result && <span className="px-1 text-[12px] text-ok">{result}</span>}
      <a
        className="flex items-center justify-between rounded-[10px] border border-line bg-surface px-3 py-2.5 text-ink-2 no-underline hover:border-line-strong hover:text-ink"
        href={supportBundleUrl(project.id)}
      >
        문제 보고용 파일 받기 <span className="font-mono text-[11px] text-faint">.zip</span>
      </a>
      <p className="px-1 text-[11px] leading-relaxed text-faint">
        로그·환경 정보·이 프로젝트 파일(주제·대사 포함)을 zip으로 받아요. API 키는 들어가지 않아요. 열어 보고 보내셔도
        돼요.
      </p>
    </div>
  );
}
