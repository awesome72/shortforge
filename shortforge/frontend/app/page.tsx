"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppBar } from "@/components/AppBar";
import { SetupNotice } from "@/components/SetupNotice";
import { STEPS } from "@/lib/labels";
import { Button, Field, Notice, inputClass } from "@/components/ui";
import { api, supportBundleUrl } from "@/lib/api";
import { STEP_IDS, type AppConfig, type ProjectRow } from "@/lib/types";

export default function Home() {
  const router = useRouter();
  const [rows, setRows] = useState<ProjectRow[] | null>(null);
  const [topic, setTopic] = useState("");
  const [audience, setAudience] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [armed, setArmed] = useState<string | null>(null); // 브라우저 확인창 대신 두 번 눌러 삭제

  const remove = async (id: string) => {
    if (armed !== id) {
      setArmed(id);
      return;
    }
    setArmed(null);
    try {
      await api.deleteProject(id);
      setRows((r) => r?.filter((x) => x.id !== id) ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    api.list().then(setRows).catch((e) => setError(e.message));
    api.config().then(setConfig).catch(() => setConfig(null));
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
    <>
    <AppBar crumb="스튜디오" />
    <SetupNotice config={config} />
    <div className="mx-auto max-w-[1040px] px-6 pt-14 pb-16">
      <span className="rounded bg-accent-tint px-[7px] py-0.5 font-mono text-[12px] text-accent">NEW PROJECT</span>
      <h1 className="mt-4 text-[38px] leading-[1.15] font-bold tracking-[-0.035em]">잘 된 숏폼의 구조를, 내 이야기로.</h1>
      <p className="mt-3 max-w-[62ch] text-[15px] text-ink-2">
        주제와 타깃을 넣으면 최근 잘 된 YouTube 숏폼을 찾아 왜 잘 됐는지 근거와 함께 정리하고, 그 구조로 30초 세로
        영상(MP4 + 자막)을 만든다. 7단계를 하나의 편집실에서.
      </p>

      <ol className="mt-8 grid grid-cols-2 gap-1 sm:grid-cols-4 lg:grid-cols-7" aria-label="제작 단계">
        {STEP_IDS.map((s) => (
          <li key={s} className="rounded-md border border-line bg-card px-3 py-2.5">
            <span className="font-mono text-[11px] text-faint">{String(STEPS[s].n).padStart(2, "0")}</span>
            <div className="text-[13px] font-semibold text-ink-2">{STEPS[s].label}</div>
            <div className="truncate text-[11.5px] text-muted">{STEPS[s].sub}</div>
          </li>
        ))}
      </ol>

      <form
        className="mt-8 grid grid-cols-2 gap-x-4 gap-y-[18px] rounded-[14px] border border-line bg-surface p-[22px]"
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
            새 프로젝트 시작
          </Button>
        </div>
      </form>

      {error && (
        <div className="mt-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      <section className="mt-10 overflow-hidden rounded-[14px] border border-line bg-surface">
        <div className="flex items-center justify-between gap-3 border-b border-line px-[18px] py-3.5">
          <h2 className="text-[13.5px] font-semibold">최근 프로젝트</h2>
          <span className="text-[12px] tabular-nums text-muted">{rows ? `${rows.length}개` : ""}</span>
        </div>
        {rows === null && !error && <p className="px-[18px] py-6 text-muted">불러오는 중…</p>}
        {rows?.length === 0 && <p className="px-[18px] py-6 text-muted">아직 프로젝트가 없다. 위에서 첫 영상을 시작한다.</p>}
        <ul>
          {rows?.map((r) => (
            <li key={r.id} className="group flex items-stretch border-t border-line first:border-t-0">
              <Link
                href={`/p/${r.id}`}
                className="flex min-w-0 flex-1 items-center justify-between gap-4 px-[18px] py-3.5 text-ink no-underline transition-colors hover:bg-white/[.02] hover:text-ink"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span
                    aria-hidden="true"
                    className="h-10 w-[23px] flex-none rounded-[5px] border border-line-strong bg-[linear-gradient(160deg,#3b3226,#0e1014)]"
                  />
                  <span className="min-w-0">
                    <span className="flex items-center gap-2">
                      {r.variant && (
                        <span className="flex-none rounded-full bg-accent-tint px-1.5 py-px text-[11px] font-semibold text-accent">
                          변형 {r.variant}
                        </span>
                      )}
                      <span className="truncate text-[14px] font-semibold tracking-[-0.01em]">{r.topic || "(주제 없음)"}</span>
                    </span>
                    <span className="font-mono text-[11.5px] text-faint">{r.id}</span>
                  </span>
                </span>
                <span className="flex-none text-right font-mono text-[12px] text-muted">
                  <span className="text-ink-2">v{r.version}</span>
                  <span className="ml-3 hidden sm:inline">{new Date(r.updated_at).toLocaleString("ko-KR")}</span>
                </span>
              </Link>
              <button
                type="button"
                onClick={() => remove(r.id)}
                onBlur={() => setArmed((a) => (a === r.id ? null : a))}
                className={`flex-none px-4 text-[12px] transition-colors ${armed === r.id ? "bg-err text-canvas" : "text-faint hover:text-err"}`}
                aria-label={`${r.topic || r.id} 삭제`}
              >
                {armed === r.id ? "한 번 더 눌러 삭제" : "삭제"}
              </button>
            </li>
          ))}
        </ul>
      </section>
      <p className="mt-10 text-[12px] text-muted">
        문제가 생기면{" "}
        <a href={supportBundleUrl()} className="text-accent hover:underline">
          문제 보고용 파일
        </a>
        (로그·환경 정보, API 키 제외)을 받아 피드백과 함께 보내 준다.
      </p>
    </div>
    </>
  );
}
