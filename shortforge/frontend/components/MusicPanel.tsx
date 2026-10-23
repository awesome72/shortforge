"use client";

import { useState } from "react";
import { api, fileUrl } from "@/lib/api";
import { MOOD_LABEL } from "@/lib/labels";
import type { Project } from "@/lib/types";
import { AudioPlayer } from "./Media";
import { Button, Panel, Seg } from "./ui";

const VOLUME = [
  { value: -24, label: "작게" },
  { value: -18, label: "보통" },
  { value: -13, label: "크게" },
];

/**
 * 6단계 배경음악: 내용에 맞춰 고른 분위기를 보여 주고, 분위기·다른 곡·음량·끄기·내 음악 올리기를 한다.
 * 바꾸면 서버가 timeline을 고쳐 7단계가 "재생성 필요"가 된다(화면은 SSE로 갱신).
 */
export function MusicPanel({
  project,
  guard,
}: {
  project: Project;
  guard: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const audio = project.timeline!.audio;
  const [working, setWorking] = useState<string | null>(null);
  const disabled = project.busy || working !== null;
  const src = fileUrl(project.id, audio.bgm, project.version);

  const act = (label: string, fn: () => Promise<unknown>) =>
    guard(async () => {
      setWorking(label);
      try {
        await fn();
      } finally {
        setWorking(null);
      }
    });
  const set = (label: string, body: Parameters<typeof api.setMusic>[1]) =>
    act(label, () => api.setMusic(project.id, body));

  const status = !audio.bgm
    ? "음악 없음"
    : audio.source === "user"
      ? `내 음악 · ${audio.bgm.split("/").pop()}`
      : `${MOOD_LABEL[audio.mood ?? ""] ?? audio.mood} 분위기 · ${audio.locked ? "직접 고름" : "내용에 맞춰 자동 추천"}`;

  return (
    <Panel title="배경음악" aside={working ? `${working}…` : "이 PC에서 합성 · 저작권 걱정 없음"} className="mb-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <div className="min-w-0 flex-[1_1_240px]">
          <div className="text-[13.5px] font-semibold text-ink">{status}</div>
          <p className="mt-1 text-[12.5px] text-muted">
            목소리가 나올 때는 음악이 자동으로 작아져요. 바꾸면 7단계에서 다시 렌더해 주세요.
          </p>
        </div>
        {src && <AudioPlayer key={src} src={src} label="배경음악" />}
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5" role="group" aria-label="분위기">
        {Object.entries(MOOD_LABEL).map(([mood, label]) => {
          const on = audio.source === "generated" && audio.bgm && audio.mood === mood;
          return (
            <button
              key={mood}
              type="button"
              aria-pressed={!!on}
              disabled={disabled}
              onClick={() => set(`${label} 곡 만드는 중`, { mood })}
              className={`rounded-full px-3 py-1.5 text-[12.5px] transition-colors disabled:cursor-not-allowed ${on ? "bg-accent font-semibold text-accent-ink" : "text-ink-2 shadow-[inset_0_0_0_1px_var(--color-line-strong)] enabled:hover:text-ink enabled:hover:shadow-[inset_0_0_0_1px_var(--color-muted)] disabled:text-faint"}`}
            >
              {label}
            </button>
          );
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2.5 border-t border-line pt-4">
        {audio.source === "generated" && audio.bgm && (
          <Button
            variant="ghost"
            className="min-h-9"
            disabled={disabled}
            onClick={() => set("다른 곡 만드는 중", { another: true })}
          >
            같은 분위기 다른 곡
          </Button>
        )}
        <label
          className={`inline-flex min-h-9 cursor-pointer items-center rounded-[10px] border border-line-strong px-4 text-[13.5px] font-semibold text-ink hover:border-muted hover:bg-card ${disabled ? "pointer-events-none text-faint" : ""}`}
          title="MP3·M4A·WAV, 25MB까지. 쓸 권리가 있는 음악만 올려 주세요"
        >
          내 음악 올리기
          <input
            type="file"
            accept=".mp3,.m4a,.wav,audio/mpeg,audio/mp4,audio/wav"
            className="sr-only"
            disabled={disabled}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) act("올리는 중", () => api.uploadMusic(project.id, f));
            }}
          />
        </label>
        {audio.bgm && (
          <Button variant="quiet" className="min-h-9" disabled={disabled} onClick={() => set("끄는 중", { off: true })}>
            음악 끄기
          </Button>
        )}
        {audio.locked && (
          <Button
            variant="quiet"
            className="min-h-9"
            disabled={disabled}
            onClick={() => set("되돌리는 중", { auto: true })}
            title="다음에 6단계를 다시 실행할 때 내용에 맞춰 다시 골라요"
          >
            자동 추천으로
          </Button>
        )}
        {audio.bgm && (
          <div className="ml-auto flex items-center gap-2.5">
            <span className="text-[12px] text-muted">음량</span>
            <div className="w-[200px]">
              <Seg
                label="배경음악 음량"
                value={VOLUME.reduce(
                  (best, v) =>
                    Math.abs(v.value - audio.bgm_gain_db) < Math.abs(best - audio.bgm_gain_db) ? v.value : best,
                  -18,
                )}
                onChange={(v) => set("음량 바꾸는 중", { gain_db: v })}
                disabled={disabled}
                options={VOLUME}
              />
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}
