"use client";

import { useState } from "react";
import { Button, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import type { BusinessBrief, Project } from "@/lib/types";

const FIELDS: { key: keyof BusinessBrief; label: string; max: number }[] = [
  { key: "shop_name", label: "가게 이름", max: 40 },
  { key: "area", label: "동네", max: 40 },
  { key: "product", label: "상품·알릴 내용", max: 80 },
  { key: "offer", label: "혜택", max: 80 },
  { key: "period", label: "기간", max: 40 },
  { key: "pride", label: "우리 가게 자랑", max: 80 },
  { key: "action", label: "손님이 할 일", max: 40 },
];

/** 만든 뒤에도 가게 정보를 고쳐 처음부터 다시 만든다 (주제 칸에 가게 정보를 적던 막다른 길) */
export function ShopInfoEditor({
  project,
  act,
}: {
  project: Project;
  act: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const brief = project.input?.business;
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<BusinessBrief | null>(brief ?? null);
  if (!brief || !draft || !project.input) return null;
  const input = project.input;
  const needOffer = draft.purpose === "promotion" && !draft.offer.trim();

  const save = () =>
    act(async () => {
      // 주제를 비우면 서버가 가게 정보로 다시 만든다. 검색어도 새 정보로 다시 만든다
      const trimmed = Object.fromEntries(
        Object.entries(draft).map(([k, v]) => [k, typeof v === "string" ? v.trim() : v]),
      ) as BusinessBrief;
      await api.patch(project.id, "input", {
        ...input,
        business: trimmed,
        topic: "",
        keywords: [],
        keywords_auto: [],
        keywords_topic: "",
      });
      setOpen(false);
      await api.runAll(project.id, "s1", "s6");
    });

  if (!open)
    return (
      <button
        type="button"
        disabled={project.busy}
        onClick={() => {
          setDraft(brief);
          setOpen(true);
        }}
        className="mt-2 rounded-md border border-line-strong px-3 py-1 text-[13px] text-ink-2 hover:text-ink disabled:opacity-50"
      >
        가게 정보 고치기
      </button>
    );

  return (
    <div className="mt-3 flex max-w-[860px] flex-col gap-3 rounded-2xl border border-line bg-surface px-5 py-4">
      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map((f) => (
          <label key={f.key} className="flex min-w-0 flex-col gap-1 text-[13px] font-semibold">
            {f.label}
            <input
              className={`${inputClass} font-normal`}
              value={String(draft[f.key] ?? "")}
              maxLength={f.max}
              onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
            />
          </label>
        ))}
      </div>
      <p className="text-[12.5px] text-muted">
        처음부터 다시 만들어요. 사진은 그대로예요. 직접 고친 대사는 사라져요.
      </p>
      {needOffer && <p className="text-[13px] text-stale-strong">할인·이벤트 영상은 혜택을 적어 주세요.</p>}
      <div className="flex flex-wrap gap-3">
        <Button onClick={save} disabled={project.busy || !draft.shop_name.trim() || needOffer}>
          저장하고 처음부터 다시 · 약 4분
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          닫기
        </Button>
      </div>
    </div>
  );
}
