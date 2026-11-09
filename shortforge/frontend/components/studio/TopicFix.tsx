"use client";

import { useState } from "react";
import { Button, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

/** 실패 안내 안에서 주제를 고쳐 처음부터 다시 찾는다 (전문가 화면으로 넘어가던 막다른 길).
 *  주제가 바뀌면 서버가 자동 검색어·해외 검색어를 새로 만든다(직접 고친 검색어는 그대로). */
export function TopicFix({
  project,
  act,
}: {
  project: Project;
  act: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [topic, setTopic] = useState(project.input?.topic ?? "");
  const input = project.input;
  if (!input) return null;
  const next = topic.trim();

  if (!open)
    return (
      <button
        type="button"
        className="inline-flex min-h-9 items-center rounded-ctl border border-line-strong bg-card px-3.5 text-sm font-semibold text-ink hover:bg-surface"
        onClick={() => {
          setTopic(input.topic);
          setOpen(true);
        }}
      >
        주제 고치기
      </button>
    );

  return (
    <form
      className="flex w-full flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!next || next === input.topic) return;
        act(async () => {
          // 예전 프로젝트는 자동 검색어 기록(keywords_topic)이 없어 서버가 다시 만들지 않는다: 직접 비운다
          const reset = input.keywords_topic ? {} : { keywords: [], keywords_auto: [], world_keywords: [] };
          await api.patch(project.id, "input", { ...input, topic: next, ...reset });
          await api.runAll(project.id, "s1", "s6");
        });
      }}
    >
      <input
        aria-label="새 주제"
        className={`${inputClass} min-w-[220px] flex-1`}
        value={topic}
        maxLength={120}
        autoFocus
        onChange={(e) => setTopic(e.target.value)}
      />
      <Button type="submit" disabled={project.busy || !next || next === input.topic}>
        바꾸고 처음부터 다시 · 약 4분
      </Button>
      <Button variant="ghost" type="button" onClick={() => setOpen(false)}>
        닫기
      </Button>
    </form>
  );
}
