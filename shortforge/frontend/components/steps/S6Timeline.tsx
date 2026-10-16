"use client";

import { useState } from "react";
import { StepActions, StepHeader } from "../StepActions";
import { TimelinePreview } from "../TimelinePreview";
import type { StepProps } from "../Workspace";
import { Mono } from "../ui";

const ENGINES = [
  { id: "ffmpeg", label: "엔진: FFmpeg", enabled: true },
  { id: "remotion", label: "Remotion (M3)", enabled: false },
  { id: "wan", label: "Wan I2V · GPU (M3)", enabled: false },
];

export function S6Timeline({ project, controls, progress }: StepProps) {
  const tl = project.timeline;
  const [raw, setRaw] = useState(false);
  const total = tl?.scenes.reduce((sum, s) => sum + (typeof s.duration === "number" ? s.duration : 0), 0) ?? 0;

  return (
    <section>
      <StepHeader
        step="s6"
        title="Timeline Spec"
        desc="영상 엔진에 그대로 넣는 기계용 지시서. 경로·길이는 규칙으로 정하고(실제 음성 길이 + 여백), LLM은 장면별 모션·전환·자막 스타일만 고른다."
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {ENGINES.map((e) => (
          <span
            key={e.id}
            className={`rounded-full border px-3 py-1 text-[13px] ${e.enabled ? "border-ink bg-ink text-surface" : "border-line bg-card text-muted"}`}
            title={e.enabled ? "" : "M3에서 어댑터 추가 예정"}
          >
            {e.label}
          </span>
        ))}
      </div>
      {!tl ? (
        <p className="rounded-lg border border-dashed border-line-dash bg-surface p-6 text-center text-muted">
          아직 지시서를 만들지 않았다.
        </p>
      ) : (
        <>
          <div className="mb-4 rounded-[10px] border border-line bg-card p-4">
            <TimelinePreview projectId={project.id} timeline={tl} version={project.version} />
          </div>
          <div className="overflow-x-auto rounded-[10px] border border-line bg-card">
            <table className="w-full min-w-[640px] border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-line text-left text-[12px] whitespace-nowrap text-muted">
                  {["장면", "길이", "모션", "전환", "자막", "텍스트"].map((h) => (
                    <th key={h} className="px-3 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tl.scenes.map((s) => (
                  <tr key={s.id} className="border-b border-line last:border-0">
                    <td className="px-3 py-2 font-medium">{s.id}</td>
                    <td className="px-3 py-2">
                      <Mono>{typeof s.duration === "number" ? `${s.duration.toFixed(2)}s` : "auto"}</Mono>
                    </td>
                    <td className="px-3 py-2">
                      <Mono>
                        {s.motion.type} {s.motion.amount}
                      </Mono>
                    </td>
                    <td className="px-3 py-2">
                      <Mono>
                        {s.transition.type}
                        {s.transition.type !== "cut" && ` ${s.transition.dur}s`}
                      </Mono>
                    </td>
                    <td className="px-3 py-2">
                      <Mono>{s.caption.style}</Mono>
                    </td>
                    <td className="max-w-[280px] truncate px-3 py-2 text-muted">{s.caption.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[13px] text-muted">
            <span>
              합계 <Mono className="text-ink">{total.toFixed(2)}초</Mono> · {tl.canvas.w}×{tl.canvas.h} {tl.canvas.fps}fps ·
              자막 {tl.subtitles.source === "tts" ? "TTS 어절 타이밍" : "Whisper"} 번인
            </span>
            <button type="button" className="text-accent hover:underline" onClick={() => setRaw(!raw)}>
              {raw ? "JSON 접기" : "JSON 보기"}
            </button>
          </div>
          {raw && (
            <pre className="mt-2 max-h-[420px] overflow-auto rounded-[10px] border border-line bg-ink p-4 font-mono text-[12px] leading-relaxed text-canvas">
              {JSON.stringify(tl, null, 2)}
            </pre>
          )}
        </>
      )}
      <StepActions
        project={project}
        step="s6"
        controls={controls}
        progress={progress}
        primaryLabel={tl ? "지시서 다시 만들기 (S6 실행)" : "편집 지시서 만들기 (S6 실행)"}
        next="s7"
      />
    </section>
  );
}
