"use client";

import { useEffect, useState } from "react";
import { api, fileUrl } from "@/lib/api";
import type { PublishKit } from "@/lib/types";

/** 업로드 전 체크리스트와 설명란 문구 (AI 고지·사진 출처·해시태그). 체크 상태는 이 브라우저에만 기억한다. */
export function PublishChecklist({ projectId, version }: { projectId: string; version: number }) {
  const [kit, setKit] = useState<PublishKit | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [copied, setCopied] = useState(false);
  const [cover, setCover] = useState<{ busy: boolean; error?: string }>({ busy: false });
  const [coverText, setCoverText] = useState<string | null>(null); // null = 아직 고치지 않음
  const storeKey = `sf-publish-${projectId}`;

  useEffect(() => {
    api
      .publish(projectId)
      .then(setKit)
      .catch(() => setKit(null));
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
  const title = coverText ?? kit.cover_title;
  const edited = title.trim() !== kit.cover_title;
  const makeCover = async () => {
    setCover({ busy: true });
    try {
      const r = await api.makeCover(projectId, edited ? title : undefined);
      setKit({ ...kit, cover: r.cover, cover_title: r.cover_title });
      setCoverText(null);
      setCover({ busy: false });
    } catch (e) {
      setCover({ busy: false, error: (e as Error).message });
    }
  };
  const coverSrc = fileUrl(projectId, kit.cover, version);

  return (
    <section className="overflow-hidden rounded-[14px] border border-line bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-line px-[18px] py-3.5">
        <h3 className="text-[13.5px] font-semibold">업로드 전 체크리스트</h3>
        <span
          className={`rounded-full px-2.5 py-[3px] text-[11.5px] font-medium ${open ? "bg-stale-tint text-stale" : "bg-ok-tint text-ok"}`}
        >
          {open ? `${open}개 남음` : "모두 확인"}
        </span>
      </div>
      <div className="grid gap-5 p-[18px] lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-2">
          {kit.checklist.map((c) => (
            <label key={c.id} className="flex items-start gap-2.5 text-[13px] leading-relaxed">
              <input
                type="checkbox"
                className="mt-0.5 size-3.5 flex-none accent-accent"
                checked={c.auto || !!checked[c.id]}
                disabled={c.auto}
                onChange={() => toggle(c.id)}
              />
              <span className={c.auto ? "text-muted" : "text-ink-2"}>{c.text}</span>
            </label>
          ))}
        </div>
        <div className="min-w-0">
          <div className="mb-2 flex items-center justify-between text-[12px] text-muted">
            <span>YouTube 설명란 문구</span>
            <button
              type="button"
              className="rounded-md border border-line-strong px-2.5 py-1 text-[12px] text-ink-2 hover:border-muted hover:text-ink"
              onClick={copy}
            >
              {copied ? "복사됨" : "복사"}
            </button>
          </div>
          <pre className="max-h-48 overflow-auto rounded-[10px] border border-line bg-sunken px-3.5 py-3 font-sans text-[12.5px] leading-[1.7] whitespace-pre-wrap text-ink-2">
            {kit.description}
          </pre>
          <div className="mt-4 flex items-start gap-3.5">
            {coverSrc ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={coverSrc}
                alt="커버 미리보기"
                className="aspect-[9/16] w-[84px] flex-none rounded-lg border border-line-strong object-cover"
              />
            ) : (
              <div className="grid aspect-[9/16] w-[84px] flex-none place-items-center rounded-lg border border-dashed border-line-strong text-[11px] text-faint">
                커버
              </div>
            )}
            <div className="flex min-w-0 flex-col gap-2 text-[12.5px]">
              <div className="font-medium text-ink-2">커버 이미지 (썸네일)</div>
              <p className="text-muted">
                첫 장면에 문구를 얹은 1080×1920 한 장이에요. YouTube 앱에서 Shorts 썸네일로 고르거나 다른 플랫폼 커버로
                써요.
              </p>
              <label className="flex flex-col gap-1">
                <span className="text-[12px] text-muted">커버 문구 · 줄을 나누려면 / 를 넣어요 · 비우면 4단계 제목</span>
                <input
                  className="min-w-0 rounded-[8px] border border-line-strong bg-sunken px-2.5 py-1.5 text-[13px] text-ink outline-none focus:border-accent"
                  value={title}
                  maxLength={60}
                  placeholder="예: 은퇴 후 30년 / 두 번째 인생 지도"
                  onChange={(e) => setCoverText(e.target.value)}
                />
              </label>
              <div className="flex flex-wrap items-center gap-2">
                {kit.cover && !edited ? (
                  <a
                    href={fileUrl(projectId, kit.cover, version, true) ?? undefined}
                    className="rounded-md border border-line-strong px-2.5 py-1 text-[12px] text-ink-2 no-underline hover:border-muted hover:text-ink"
                  >
                    커버 다운로드
                  </a>
                ) : (
                  <button
                    type="button"
                    disabled={cover.busy}
                    className="rounded-md border border-line-strong px-2.5 py-1 text-[12px] text-ink-2 hover:border-muted hover:text-ink disabled:opacity-50"
                    onClick={makeCover}
                  >
                    {cover.busy ? "만드는 중…" : kit.cover ? "이 문구로 다시 만들기" : "커버 만들기"}
                  </button>
                )}
                {cover.error && <span className="text-[12px] text-err">{cover.error}</span>}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
