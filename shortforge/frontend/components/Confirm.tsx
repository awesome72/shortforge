"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Button } from "./ui";

/**
 * 확인은 이 한 가지 모양만 쓴다 (E2, 2026-11-07). 무엇을 잃는지로 세 종류:
 * - money: 돈이 나간다. 금액을 보여 주고, 확인 버튼은 0.9초 뒤에야 눌린다(습관적인 두 번 누르기 방지)
 * - out: 내 사진·그림이 밖(외부 서버)으로 나간다. 무엇이 어디로 가는지 한 줄
 * - lose: 고친 내용·만든 것이 사라진다. 잃는 것을 개수로
 * 버튼은 '동사 + 결과'와 '취소'로 고정한다. 누른 버튼 바로 아래에 연다.
 */
export type ConfirmKind = "money" | "out" | "lose";

export const ARM_DELAY_MS = 900;

const BORDER: Record<ConfirmKind, string> = {
  money: "border-accent/50",
  out: "border-role-problem/50",
  lose: "border-stale-line",
};

export type ChipTone = "plain" | "money" | "out" | "lose";
const CHIP: Record<ChipTone, string> = {
  plain: "border-line-strong text-ink-2",
  money: "border-accent/45 text-accent",
  out: "border-role-problem/45 text-role-problem",
  lose: "border-stale-line text-stale",
};

export type ChipItem = string | { text: string; tone: ChipTone };

/** 문장 대신 쓰는 짧은 표시 (시간·비용·외부 전송·잃는 것) */
export function Chips({ items, className = "" }: { items: ChipItem[]; className?: string }) {
  return (
    <span className={`flex flex-wrap gap-1.5 ${className}`}>
      {items.map((c) => {
        const { text, tone } = typeof c === "string" ? { text: c, tone: "plain" as const } : c;
        return (
          <span key={text} className={`rounded-full border px-2 py-0.5 text-[12px] tabular-nums ${CHIP[tone]}`}>
            {text}
          </span>
        );
      })}
    </span>
  );
}

export function ConfirmInline({
  kind,
  question,
  chips = [],
  note,
  confirmLabel,
  onConfirm,
  onCancel,
  disabled = false,
}: {
  kind: ConfirmKind;
  question: string;
  chips?: ChipItem[];
  note?: ReactNode; // 꼭 보여야 하는 한 줄 (법적 경고 등). 긴 설명은 넣지 않는다
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  disabled?: boolean;
}) {
  const [ready, setReady] = useState(kind !== "money");
  useEffect(() => {
    // 열린 채 종류가 money로 바뀌어도 다시 0.9초를 기다린다
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReady(kind !== "money");
    if (kind !== "money") return;
    const t = window.setTimeout(() => setReady(true), ARM_DELAY_MS);
    return () => window.clearTimeout(t);
  }, [kind]);
  return (
    <div
      role="group"
      aria-label={question}
      className={`flex flex-col gap-2 rounded-xl border bg-card px-3.5 py-3 text-[13.5px] ${BORDER[kind]}`}
    >
      <p className="font-semibold text-ink">{question}</p>
      {chips.length > 0 && <Chips items={chips} />}
      {note && <p className="text-[13px] text-stale-strong">{note}</p>}
      <div className="flex flex-wrap gap-2">
        <Button className="min-h-9" disabled={disabled || !ready} onClick={onConfirm}>
          {confirmLabel}
        </Button>
        <Button variant="ghost" className="min-h-9" onClick={onCancel}>
          취소
        </Button>
      </div>
    </div>
  );
}

/** 장면 하나를 AI로 움직이기 전 확인 (쉬운 화면·전문가 화면 공통). 묻지 않아도 되면 null */
export function motionConfirm({
  label,
  free,
  price,
  mine,
  mode,
}: {
  label: string; // "장면 3"
  free: boolean; // 호출당 요금이 없는 방식 (공개 데모 서버)
  price: number;
  mine: boolean; // 내 사진 장면 (밖으로 나간다)
  mode?: string; // hobby | business | listing
}): {
  kind: ConfirmKind;
  question: string;
  chips: ChipItem[];
  note?: string;
  confirmLabel: string;
} | null {
  if (free && !mine) return null; // 설정에서 이미 동의했고, 버튼에 '외부 전송'이 보인다
  const chips: ChipItem[] = [];
  if (!free) chips.push({ text: `$${price.toFixed(2)}`, tone: "money" }, "몇 분");
  else chips.push("무료", "30초쯤");
  if (mine) {
    chips.push({ text: free ? "사진이 외부 데모 서버로 가요" : "사진이 Hugging Face로 가요", tone: "out" });
    chips.push("다른 사람이 나오면 넣지 마세요", "정사각형·가로 사진은 양옆이 잘려요");
    if (mode === "listing") chips.push("방·가구 모양이 바뀔 수 있어요");
    else if (mode === "business") chips.push("음식·글자 모양이 바뀔 수 있어요");
    chips.push("다르면 '원래대로'");
  } else {
    chips.push({ text: "Hugging Face 크레딧", tone: "out" });
  }
  return {
    kind: free ? "out" : "money",
    // 조사(을/를)가 번호마다 달라 장면 번호는 묻는 말에 넣지 않는다 (확인 상자는 그 장면 바로 아래에 열린다)
    question: mine ? `${label} · 내 사진을 AI로 움직일까요?` : `${label} · AI로 움직일까요?`,
    chips,
    note: mine && mode === "listing" ? "실제와 다른 매물 사진은 부당 광고예요. 만든 뒤 끝까지 봐 주세요." : undefined,
    confirmLabel: free ? "사진 보내고 움직이기" : `$${price.toFixed(2)} 쓰고 시작`,
  };
}
