"use client";

import { useState } from "react";
import { DEAL, FIELDS, PROPERTY } from "@/components/ListingForm";
import { Button, Seg, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import type { ListingBrief, Project } from "@/lib/types";

// 사무소·장점 칸 (매물 칸은 ListingForm의 FIELDS를 그대로 쓴다)
const EXTRA: { key: keyof ListingBrief; label: string; max: number; need: boolean }[] = [
  { key: "office_name", label: "사무소 이름", max: 40, need: true },
  { key: "agent_name", label: "대표 공인중개사", max: 20, need: true },
  { key: "office_address", label: "사무소 소재지", max: 80, need: true },
  { key: "office_phone", label: "연락처", max: 20, need: true },
  { key: "reg_no", label: "등록번호", max: 30, need: true },
  { key: "highlights", label: "장점 (있으면)", max: 120, need: false },
  { key: "nearby", label: "주변 (있으면, 도보 기준)", max: 80, need: false },
  { key: "action", label: "손님이 할 일", max: 40, need: false },
];
// 바뀌면 검색어·참고 영상부터 다시 찾는 칸 (주제가 이 값으로 만들어진다)
const TOPIC_KEYS: (keyof ListingBrief)[] = ["location", "complex_name", "prop_type", "deal"];

/** 만든 뒤에도 매물 정보를 고친다. 가격 오타 하나에 새로 만들어야 하던 막다른 길 */
export function ListingInfoEditor({
  project,
  act,
}: {
  project: Project;
  act: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const brief = project.input?.listing;
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<ListingBrief | null>(brief ?? null);
  if (!brief || !draft || !project.input) return null;
  const input = project.input;
  const fields = [...FIELDS, ...EXTRA];
  const missing = fields.filter((f) => f.need && !String(draft[f.key] ?? "").trim());
  const topicChanged = TOPIC_KEYS.some((k) => String(draft[k]).trim() !== String(brief[k]).trim());

  const save = () =>
    act(async () => {
      const trimmed = Object.fromEntries(
        Object.entries(draft).map(([k, v]) => [k, typeof v === "string" ? v.trim() : v]),
      ) as unknown as ListingBrief;
      if (topicChanged) {
        // 동네·종류가 바뀌면 주제와 검색어를 새로 만들어 참고 영상부터 다시 찾는다
        await api.patch(project.id, "input", { ...input, listing: trimmed, topic: "", keywords: [], keywords_auto: [], keywords_topic: "" });
        setOpen(false);
        await api.runAll(project.id, "s1", "s6");
      } else {
        // 가격·면적·사무소 정보만 바뀌면 대본(가격 대사)부터 다시 만들고 끝 카드에 반영한다
        await api.patch(project.id, "input", { ...input, listing: trimmed });
        setOpen(false);
        await api.runAll(project.id, "s4", "s6");
      }
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
        매물 정보 고치기
      </button>
    );

  return (
    <div className="mt-3 flex max-w-[860px] flex-col gap-3 rounded-2xl border border-line bg-surface px-5 py-4">
      <div className="flex flex-wrap gap-4">
        <Seg label="매물 종류" value={draft.prop_type} onChange={(v) => setDraft({ ...draft, prop_type: v })} options={PROPERTY} />
        <Seg label="거래 형태" value={draft.deal} onChange={(v) => setDraft({ ...draft, deal: v })} options={DEAL} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map((f) => (
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
        {topicChanged
          ? "동네나 매물 종류가 바뀌어 비슷한 영상부터 다시 찾고 대사를 새로 만들어요."
          : "대사와 영상 끝 매물 정보를 새로 만들어요. 비슷한 영상은 다시 찾지 않아요."}{" "}
        올린 사진은 그대로 써요.
      </p>
      {project.status.s5 !== "idle" && (
        <p className="text-[13px] text-stale-strong">대사를 새로 쓰므로 다듬기에서 직접 고친 대사는 사라져요.</p>
      )}
      {missing.length > 0 && (
        <p className="text-[13px] text-stale-strong">{missing.map((f) => f.label).join(", ")} 칸을 채워 주세요.</p>
      )}
      <div className="flex flex-wrap gap-3">
        <Button onClick={save} disabled={project.busy || missing.length > 0}>
          고치고 다시 만들기
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          닫기
        </Button>
      </div>
    </div>
  );
}
