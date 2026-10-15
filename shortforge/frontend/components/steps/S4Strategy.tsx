"use client";

import { useState } from "react";
import { FACTOR_LABEL, ROLE_LABEL } from "@/lib/labels";
import type { Strategy } from "@/lib/types";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Button, Card, Field, inputClass } from "../ui";

export function S4Strategy({ project, controls, save, progress }: StepProps) {
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
  const setTitle = (i: number, t: string) => setDraft((d) => d && { ...d, titles: d.titles.map((x, j) => (j === i ? t : x)) });

  return (
    <section>
      <StepHeader
        step="s4"
        title={`${project.input?.duration_sec ?? 30}초 스토리보드`}
        desc="성공 요인 × 내 입력을 장면 단위로 바꾼다. 장면 카드가 5단계 자산의 단위가 된다. 대사를 고치면 5단계부터 재생성 필요."
      />
      {!draft ? (
        <p className="rounded-lg border border-dashed border-line-dash bg-surface p-6 text-center text-muted">
          아직 전략을 만들지 않았다.
        </p>
      ) : (
        <>
          <div className="flex flex-col gap-2.5">
            {draft.scenes.map((s, i) => (
              <div key={s.id} className="flex flex-wrap gap-3.5 rounded-[10px] border border-line bg-card px-4 py-3.5">
                <div className="w-[96px] flex-none">
                  <div className="font-mono text-[12px] text-muted">
                    {s.start}–{s.end}s
                  </div>
                  <div className="mt-1 inline-block rounded-full bg-canvas px-2 py-0.5 text-[12px] font-medium whitespace-nowrap">
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
                  <div className="mt-0.5 text-[12px] text-accent">
                    요인: {s.factor_refs.map((f) => FACTOR_LABEL[f]).join(" · ") || "—"}
                  </div>
                </div>
              </div>
            ))}
          </div>

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
          <Field label="스타일 시드 (모든 장면 이미지 프롬프트에 공통으로 붙는다)">
            <input className={`${inputClass} mt-3 font-mono text-[12px]`} value={draft.style_seed} readOnly />
          </Field>

          <div className="mt-4 flex flex-wrap items-center gap-2.5">
            <Button variant="ghost" disabled={!dirty || project.busy} onClick={() => save("strategy", draft)}>
              {dirty ? "전략 저장" : "저장됨"}
            </Button>
            {dirty && <span className="text-[13px] text-stale">저장하면 5~7단계에 &quot;재생성 필요&quot;가 붙는다</span>}
          </div>
        </>
      )}
      <StepActions
        project={project}
        step="s4"
        controls={controls}
        progress={progress}
        primaryLabel={saved ? "전략 다시 만들기 (S4 실행)" : "전략 만들기 (S4 실행)"}
        next="s5"
      />
    </section>
  );
}
