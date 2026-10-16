"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Field, Notice, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import type { ProjectRow } from "@/lib/types";

export default function Home() {
  const router = useRouter();
  const [rows, setRows] = useState<ProjectRow[] | null>(null);
  const [topic, setTopic] = useState("");
  const [audience, setAudience] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.list().then(setRows).catch((e) => setError(e.message));
  }, []);

  const create = async () => {
    setBusy(true);
    try {
      const p = await api.create({ topic: topic.trim(), audience: audience.trim() });
      router.push(`/p/${p.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl px-6 py-14">
      <div className="font-mono text-[12px] tracking-wider text-accent">SHORTFORGE · 비용 ₩0</div>
      <h1 className="mt-2 font-display text-[34px] font-bold tracking-tight">잘 된 숏폼의 구조를, 내 이야기로.</h1>
      <p className="mt-2 text-muted">
        개인 입력부터 레퍼런스 분석, 전략, 렌더까지 — 7단계를 하나의 워크스페이스에서.
      </p>

      <form
        className="mt-8 grid grid-cols-2 gap-4 rounded-xl border border-line bg-surface p-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (topic.trim()) create();
        }}
      >
        <Field label="무엇을 만들고 싶나요?" wide>
          <input
            className={inputClass}
            value={topic}
            placeholder="예: 퇴근 후 10분 홈트로 3개월간 바뀐 점"
            onChange={(e) => setTopic(e.target.value)}
            autoFocus
          />
        </Field>
        <Field label="타깃 시청자" wide>
          <input
            className={inputClass}
            value={audience}
            placeholder="예: 30대 직장인"
            onChange={(e) => setAudience(e.target.value)}
          />
        </Field>
        <div className="col-span-2">
          <Button type="submit" disabled={!topic.trim() || busy}>
            새 프로젝트 시작 →
          </Button>
        </div>
      </form>

      {error && (
        <div className="mt-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      <h2 className="mt-10 mb-3 font-mono text-[12px] tracking-wider text-muted">최근 프로젝트</h2>
      {rows === null && !error && <p className="text-muted">불러오는 중…</p>}
      {rows?.length === 0 && <p className="text-muted">아직 프로젝트가 없다.</p>}
      <div className="flex flex-col gap-2">
        {rows?.map((r) => (
          <Link
            key={r.id}
            href={`/p/${r.id}`}
            className="flex items-center justify-between gap-4 rounded-lg border border-line bg-card px-4 py-3 text-ink no-underline hover:border-line-strong hover:text-ink"
          >
            <span className="flex min-w-0 items-center gap-2">
              {r.variant && (
                <span className="flex-none rounded-full bg-accent-tint px-1.5 py-px text-[11px] font-medium text-accent-strong">
                  변형 {r.variant}
                </span>
              )}
              <span className="truncate font-medium">{r.topic || "(주제 없음)"}</span>
            </span>
            <span className="flex-none font-mono text-[12px] text-muted">
              v{r.version} · {new Date(r.updated_at).toLocaleString("ko-KR")}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
