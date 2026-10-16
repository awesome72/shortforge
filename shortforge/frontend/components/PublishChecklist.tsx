"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PublishKit } from "@/lib/types";
import { Card } from "./ui";

/** 업로드 전 체크리스트와 설명란 문구 (AI 고지·사진 출처·해시태그). 체크 상태는 이 브라우저에만 기억한다. */
export function PublishChecklist({ projectId, version }: { projectId: string; version: number }) {
  const [kit, setKit] = useState<PublishKit | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState(false);
  const storeKey = `sf-publish-${projectId}`;

  useEffect(() => {
    api.publish(projectId).then(setKit).catch(() => setKit(null));
  }, [projectId, version]);

  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setChecked(JSON.parse(localStorage.getItem(storeKey) ?? "{}"));
    } catch {
      /* 저장소를 쓸 수 없는 환경이면 체크는 기억하지 않는다 */
    }
  }, [storeKey]);

  if (!kit) return null;

  const toggle = (id: string) => {
    const next = { ...checked, [id]: !checked[id] };
    setChecked(next);
    try {
      localStorage.setItem(storeKey, JSON.stringify(next));
    } catch {
      /* 무시 */
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(kit.description);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  const open = kit.checklist.filter((c) => !c.auto && !checked[c.id]).length;

  return (
    <Card>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-semibold">업로드 전 체크리스트</span>
        <span className={`text-[12px] ${open ? "text-stale" : "text-ok"}`}>
          {open ? `${open}개 남음` : "모두 확인"}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        {kit.checklist.map((c) => (
          <label key={c.id} className="flex items-start gap-2 text-[12px] leading-relaxed">
            <input
              type="checkbox"
              className="mt-0.5 size-3.5 flex-none accent-accent"
              checked={c.auto || !!checked[c.id]}
              disabled={c.auto}
              onChange={() => toggle(c.id)}
            />
            <span className={c.auto ? "text-muted" : ""}>{c.text}</span>
          </label>
        ))}
      </div>
      <div className="mt-3 mb-1 flex items-center justify-between text-[12px] text-muted">
        <span>YouTube 설명란 문구</span>
        <button type="button" className="text-accent hover:underline" onClick={copy}>
          {copied ? "복사됨" : "복사"}
        </button>
      </div>
      <pre className="max-h-40 overflow-auto rounded-md border border-line bg-surface p-2 text-[12px] whitespace-pre-wrap">
        {kit.description}
      </pre>
    </Card>
  );
}
