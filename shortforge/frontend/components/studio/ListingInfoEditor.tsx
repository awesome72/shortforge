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
// 대사(AI)가 읽는 칸. 이 밖의 칸은 가격·연락 대사만 바꾸거나 끝 화면에만 쓴다 (서버와 같은 나눔)
const SCRIPT_KEYS: (keyof ListingBrief)[] = ["highlights", "nearby"];
// 코드가 넣는 가격·연락 대사에 쓰는 칸 (그 대사와 목소리만 몇 초 안에 바뀐다)
const LINE_KEYS: (keyof ListingBrief)[] = ["price", "move_in", "action", "office_name"];

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
  const fields = [...FIELDS, ...EXTRA];
  const missing = fields.filter((f) => f.need && !String(draft[f.key] ?? "").trim());
  const differs = (k: keyof ListingBrief) => String(draft[k]).trim() !== String(brief[k]).trim();
  const topicChanged = TOPIC_KEYS.some(differs);
  const scriptChanged = SCRIPT_KEYS.some(differs);
  // 4~6단계가 다 끝나 있지 않으면 서버는 가격만 바뀌어도 대사를 다시 쓴다 (main.set_listing)
  const ready = (["s4", "s5", "s6"] as const).every((s) => project.status[s] === "done");
  const lineChanged = LINE_KEYS.some(differs);
  const rewrite = scriptChanged || (lineChanged && !ready);
  // 이름이 동작과 같게: 카드 칸만 바뀌면 아무것도 다시 만들지 않는다
  const saveLabel = topicChanged
    ? "저장하고 처음부터 다시 · 약 4분"
    : rewrite
      ? "저장하고 대사 다시 쓰기 · 약 3분"
      : "저장하기";

  const save = () =>
    act(async () => {
      const trimmed = Object.fromEntries(
        Object.entries(draft).map(([k, v]) => [k, typeof v === "string" ? v.trim() : v]),
      ) as unknown as ListingBrief;
      // 서버가 바뀐 칸을 보고 가장 적게 다시 한다. 가격·면적만이면 AI 없이 가격 대사와 끝 화면만 바뀐다
      const { redo } = await api.setListing(project.id, trimmed);
      setOpen(false);
      if (redo === "s1" || redo === "s4") await api.runAll(project.id, redo, "s6");
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
          ? "참고 영상부터 다시 찾고 대사를 새로 써요."
          : rewrite
            ? "대사를 새로 써요."
            : lineChanged
              ? "가격·연락 대사만 바뀌어요. 영상은 다시 완성해야 들어가요."
              : "끝 화면 정보만 바뀌어요. 영상은 다시 완성해야 들어가요."}{" "}
        사진은 그대로예요.
      </p>
      {(topicChanged || scriptChanged || (["s4", "s5", "s6"] as const).some((s) => project.status[s] !== "done")) &&
        project.status.s5 !== "idle" && (
        <p className="text-[13px] text-stale-strong">직접 고친 대사는 사라져요.</p>
      )}
      {missing.length > 0 && (
        <p className="text-[13px] text-stale-strong">{missing.map((f) => f.label).join(", ")} 칸을 채워 주세요.</p>
      )}
      <div className="flex flex-wrap gap-3">
        <Button onClick={save} disabled={project.busy || missing.length > 0}>
          {saveLabel}
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          닫기
        </Button>
      </div>
    </div>
  );
}
