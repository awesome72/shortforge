"use client";

import { useState } from "react";
import { FACTOR_LABEL, ROLE_COLOR, ROLE_LABEL } from "@/lib/labels";
import { hookWarning, moveScene, renumber } from "@/lib/storyboard";
import type { Strategy } from "@/lib/types";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Button, Card, Field, Notice, inputClass } from "../ui";

export function S4Strategy({ project, controls, save, progress, scene, focusScene }: StepProps) {
  const saved = project.strategy;
  const [draft, setDraft] = useState<Strategy | null>(saved);
  const [syncedVersion, setSyncedVersion] = useState(project.version);
  if (project.version !== syncedVersion) {
    setSyncedVersion(project.version);
    setDraft(saved);
  }
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);

  const setLine = (i: number, line: string) =>
    setDraft((d) => d && { ...d, scenes: d.scenes.map((s, j) => (j === i ? { ...s, line } : s)) });
  const setTitle = (i: number, t: string) =>
    setDraft((d) => d && { ...d, titles: d.titles.map((x, j) => (j === i ? t : x)) });

  // 장면 재정렬 (F-4.3): 끌어서 놓거나 ▲▼로 옮긴다. ID는 저장할 때 순서대로 다시 붙인다
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [overIdx, setOverIdx] = useState<number | null>(null);
  const move = (i: number, j: number) => setDraft((d) => d && { ...d, scenes: moveScene(d.scenes, i, j) });
  const order = draft?.scenes.map((s) => s.id).join(",") ?? "";
  const reordered = order !== (saved?.scenes.map((s) => s.id).join(",") ?? "");
  const warning = draft && reordered ? hookWarning(draft.scenes) : null;

  return (
    <section>
      <StepHeader
        step="s4"
        title={`${project.input?.duration_sec ?? 30}초 스토리보드`}
        desc="성공 요인을 내 이야기에 맞춰 장면별 대본으로 만들었어요. 대사를 고치거나 순서를 바꿀 수 있어요."
      />
      {!draft ? (
        <p className="rounded-lg border border-dashed border-line-dash bg-surface p-6 text-center text-muted">
          아직 전략을 만들지 않았어요.
        </p>
      ) : (
        <>
          <div className="mb-1.5 flex h-11 gap-[3px]" aria-label="장면별 길이">
            {draft.scenes.map((s) => (
              <div
                key={s.id}
                className="flex min-w-0 items-center overflow-hidden rounded-[5px] px-2.5 text-[12px] font-semibold whitespace-nowrap text-canvas"
                style={{ flex: Math.max(0.5, s.end - s.start), background: ROLE_COLOR[s.role] }}
                title={`${s.id} ${ROLE_LABEL[s.role]} ${s.start}–${s.end}s`}
              >
                {s.id} · {ROLE_LABEL[s.role]}
              </div>
            ))}
          </div>
          <div className="mb-[22px] flex justify-between font-mono text-[10.5px] text-faint">
            {[0, 1, 2, 3].map((k) => (
              <span key={k}>{Math.round(((draft.scenes.at(-1)?.end ?? 30) * k) / 3)}s</span>
            ))}
          </div>
          <div className="flex flex-col gap-2.5">
            {draft.scenes.map((s, i) => (
              <div
                key={s.id}
                onDragOver={(e) => {
                  if (dragIdx === null) return;
                  e.preventDefault();
                  setOverIdx(i);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  if (dragIdx !== null) move(dragIdx, i);
                  setDragIdx(null);
                  setOverIdx(null);
                }}
                onFocusCapture={() => focusScene(s.id)}
                onClick={() => focusScene(s.id)}
                className={`flex flex-wrap gap-3.5 rounded-[14px] border bg-surface px-4 py-4 ${
                  overIdx === i && dragIdx !== i ? "border-accent" : "border-line"
                } ${dragIdx === i ? "opacity-50" : ""} ${scene === s.id ? "shadow-[inset_3px_0_0_var(--color-accent)]" : ""}`}
              >
                <div className="flex flex-none flex-col items-center gap-0.5 text-muted">
                  <button
                    type="button"
                    className="leading-none hover:text-accent disabled:opacity-30"
                    disabled={project.busy || i === 0}
                    onClick={() => move(i, i - 1)}
                    aria-label={`${s.id} 위로`}
                  >
                    ▲
                  </button>
                  <span
                    draggable={!project.busy}
                    onDragStart={(e) => {
                      e.dataTransfer.effectAllowed = "move";
                      e.dataTransfer.setData("text/plain", s.id);
                      setDragIdx(i);
                    }}
                    onDragEnd={() => {
                      setDragIdx(null);
                      setOverIdx(null);
                    }}
                    className="cursor-grab px-1 text-[16px] leading-none select-none active:cursor-grabbing"
                    title="끌어서 순서 바꾸기"
                  >
                    ⠿
                  </span>
                  <button
                    type="button"
                    className="leading-none hover:text-accent disabled:opacity-30"
                    disabled={project.busy || i === draft.scenes.length - 1}
                    onClick={() => move(i, i + 1)}
                    aria-label={`${s.id} 아래로`}
                  >
                    ▼
                  </button>
                </div>
                <div className="w-[96px] flex-none">
                  <div className="font-mono text-[12px] text-muted">
                    {s.start}–{s.end}s
                  </div>
                  <div className="mt-1.5 flex items-center gap-2 text-[13px] font-semibold whitespace-nowrap">
                    <i className="size-2 flex-none rounded-[2px]" style={{ background: ROLE_COLOR[s.role] }} />
                    {s.id} · {ROLE_LABEL[s.role]}
                  </div>
                </div>
                <div className="min-w-0 flex-[1_1_260px]">
                  <textarea
                    className={`${inputClass} min-h-[44px] w-full resize-y py-2`}
                    rows={2}
                    value={s.line}
                    disabled={project.busy}
                    onChange={(e) => setLine(i, e.target.value)}
                    aria-label={`${s.id} 대사`}
                  />
                  <div className="mt-1.5 text-[12px] text-muted">화면: {s.visual}</div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {s.factor_refs.length === 0 && <span className="text-[12px] text-faint">요인 —</span>}
                    {s.factor_refs.map((f) => (
                      <span
                        key={f}
                        className="rounded-md border border-line bg-card px-2 py-0.5 text-[12px] text-ink-2"
                      >
                        {FACTOR_LABEL[f]}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {warning && (
            <div className="mt-2.5">
              <Notice tone="warn">{warning}</Notice>
            </div>
          )}

          <div className="mt-3.5 grid grid-cols-1 gap-2.5 md:grid-cols-3">
            <Card>
              <div className="mb-2 text-[12px] font-medium text-muted">제목 후보 A / B</div>
              {draft.titles.map((t, i) => (
                <input
                  key={i}
                  className={`${inputClass} mb-1.5 min-h-9 w-full`}
                  value={t}
                  disabled={project.busy}
                  onChange={(e) => setTitle(i, e.target.value)}
                  aria-label={`제목 ${i === 0 ? "A" : "B"}`}
                />
              ))}
            </Card>
            <Card>
              <div className="text-[12px] font-medium text-muted">업로드 시각</div>
              <div className="mt-1">{draft.post_time_hint}</div>
              <div className="mt-1 text-[12px] text-muted">레퍼런스 게시 시각 분포 기준</div>
            </Card>
            <Card>
              <div className="text-[12px] font-medium text-muted">차별화 포인트</div>
              <div className="mt-1">{draft.differentiator}</div>
            </Card>
          </div>
          <Field label="공통 그림 스타일 (모든 장면 이미지에 똑같이 적용돼요)">
            <input className={`${inputClass} mt-3 text-[13px]`} value={draft.style_seed} readOnly />
          </Field>

          <div className="mt-4 flex flex-wrap items-center gap-2.5">
            <Button
              variant="ghost"
              disabled={!dirty || project.busy}
              onClick={() => save("strategy", { ...draft, scenes: renumber(draft.scenes) })}
            >
              {dirty ? "전략 저장" : "저장됨"}
            </Button>
            {dirty && (
              <span className="text-[13px] text-stale">
                저장하면 5~7단계에 &quot;재생성 필요&quot;가 붙어요
                {reordered && " (장면 번호는 새 순서대로 S1부터 다시 붙어요)"}
              </span>
            )}
          </div>
        </>
      )}
      <StepActions
        project={project}
        step="s4"
        controls={controls}
        progress={progress}
        primaryLabel={saved ? "전략 다시 만들기" : "전략 만들기"}
        next="s5"
      />
    </section>
  );
}
