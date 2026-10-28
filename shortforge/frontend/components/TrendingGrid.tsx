"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtNum } from "@/lib/labels";
import type { TrendingVideo } from "@/lib/types";
import { YouTubeModal } from "./YouTubeModal";

// YouTube 영상 분류 ID (한국 인기 차트에서 쓰는 것만)
const CATEGORIES: { id: string | null; label: string }[] = [
  { id: null, label: "전체" },
  { id: "22", label: "일상" },
  { id: "26", label: "생활 정보" },
  { id: "24", label: "재미" },
  { id: "27", label: "공부" },
  { id: "17", label: "운동" },
  { id: "10", label: "음악" },
];

/** 제목에서 해시태그·괄호·이모지를 빼고 주제로 쓸 만한 말만 남긴다 */
export function topicFromTitle(title: string): string {
  return title
    .replace(/#[^\s#]+/g, "")
    .replace(/[[(【].*?[\])】]/g, "")
    .replace(/[\p{Extended_Pictographic}️]/gu, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 60);
}

/**
 * 첫 화면: 요즘 많이 보는 영상 (YouTube 인기 차트, 숏폼 먼저).
 * 누르면 크게 재생하고, "이런 영상 만들기"로 주제를 채운다. 영상은 내려받지 않고 YouTube 플레이어로만 본다.
 */
export function TrendingGrid({ onPick }: { onPick: (topic: string) => void }) {
  const [category, setCategory] = useState<string | null>(null);
  const [videos, setVideos] = useState<TrendingVideo[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [open, setOpen] = useState<TrendingVideo | null>(null);

  useEffect(() => {
    let alive = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVideos(null);
    api
      .trending(category ?? undefined)
      .then((r) => {
        if (!alive) return;
        setVideos(r.videos);
        setNotice(r.notice);
      })
      .catch((e) => alive && (setVideos([]), setNotice((e as Error).message)));
    return () => {
      alive = false;
    };
  }, [category]);

  return (
    <section className="mt-12">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[22px] font-bold tracking-[-0.02em]">요즘 많이 보는 영상</h2>
          <p className="mt-1 text-[13.5px] text-muted">마음에 드는 영상을 눌러 보고, 비슷한 영상을 만들어 보세요.</p>
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="분류">
          {CATEGORIES.map((c) => (
            <button
              key={c.label}
              type="button"
              aria-pressed={category === c.id}
              onClick={() => setCategory(c.id)}
              className="rounded-full border border-line-strong px-3.5 py-1.5 text-[13px] text-ink-2 hover:text-ink aria-pressed:border-accent aria-pressed:bg-accent-tint aria-pressed:text-accent"
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {notice && <p className="mt-4 text-[13px] text-muted">{notice}</p>}
      <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {videos === null
          ? Array.from({ length: 10 }, (_, i) => (
              <div key={i} className="sf-skel aspect-[9/16] rounded-2xl" aria-hidden="true" />
            ))
          : videos.slice(0, 20).map((v) => (
              <button
                key={v.video_id}
                type="button"
                onClick={() => setOpen(v)}
                className="group flex flex-col gap-2 text-left"
                aria-label={`${v.title} 크게 보기`}
              >
                <span className="relative block aspect-[9/16] overflow-hidden rounded-2xl border border-line-strong bg-sunken">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={v.thumbnail_url}
                    alt=""
                    loading="lazy"
                    className="h-full w-full scale-[1.34] object-cover transition-transform group-hover:scale-[1.4]"
                  />
                  <span className="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100">
                    <span className="flex size-12 items-center justify-center rounded-full bg-black/55 text-white">
                      <svg viewBox="0 0 16 16" width="18" height="18" fill="currentColor" aria-hidden="true">
                        <path d="M4.5 2.8v10.4a.6.6 0 0 0 .9.5l8.3-5.2a.6.6 0 0 0 0-1L5.4 2.3a.6.6 0 0 0-.9.5z" />
                      </svg>
                    </span>
                  </span>
                  {v.is_short && (
                    <span className="absolute top-2 left-2 rounded-full bg-black/60 px-2 py-0.5 text-[11px] text-white">
                      숏폼
                    </span>
                  )}
                </span>
                <span className="line-clamp-2 text-[13.5px] leading-snug font-medium text-ink">{v.title}</span>
                <span className="text-[12px] tabular-nums text-muted">조회 {fmtNum(v.views)}</span>
              </button>
            ))}
      </div>
      {videos?.length === 0 && !notice && (
        <p className="mt-4 text-[13px] text-muted">이 분류에는 지금 보여 줄 영상이 없어요.</p>
      )}

      {open && (
        <YouTubeModal
          videoId={open.video_id}
          title={open.title}
          vertical={open.is_short}
          onClose={() => setOpen(null)}
          action={{
            label: "이런 영상 만들기",
            run: () => {
              onPick(topicFromTitle(open.title));
              setOpen(null);
            },
          }}
        />
      )}
    </section>
  );
}
