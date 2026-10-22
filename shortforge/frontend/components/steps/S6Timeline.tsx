"use client";

import { useState } from "react";
import { ROLE_COLOR, ROLE_LABEL } from "@/lib/labels";
import { StepActions, StepHeader } from "../StepActions";
import { TimelinePreview } from "../TimelinePreview";
import type { StepProps } from "../Workspace";
import { Mono, Panel, Seg } from "../ui";

type Engine = "ffmpeg" | "remotion" | "wan";

const ENGINES: {
  value: Engine;
  label: string;
  disabled?: boolean;
  title?: string;
}[] = [
  { value: "ffmpeg", label: "FFmpeg" },
  {
    value: "remotion",
    label: "Remotion",
    disabled: true,
    title: "M3에서 어댑터 추가 예정",
  },
  {
    value: "wan",
    label: "Wan I2V (GPU)",
    disabled: true,
    title: "M3에서 어댑터 추가 예정 (로컬 GPU 필요)",
  },
];

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

/** JSON 한 줄을 키·문자열·숫자 색으로 칠한다 (먼저 이스케이프하므로 사용자 문구가 HTML로 해석되지 않는다) */
function highlight(line: string): string {
  return esc(line)
    .replace(/(&quot;[^&]*?&quot;)(\s*:)/g, '<span class="text-[#9fb7e8]">$1</span>$2')
    .replace(/(:\s*)(&quot;.*?&quot;)/g, '$1<span class="text-[#a9d3a0]">$2</span>')
    .replace(/(:\s*)(-?\d+(?:\.\d+)?|true|false|null)/g, '$1<span class="text-accent">$2</span>');
}

export function S6Timeline({ project, controls, progress }: StepProps) {
  const tl = project.timeline;
  const [raw, setRaw] = useState(false);
  const total = tl?.scenes.reduce((sum, s) => sum + (typeof s.duration === "number" ? s.duration : 0), 0) ?? 0;
  const roleOf = Object.fromEntries((project.strategy?.scenes ?? []).map((s) => [s.id, s.role]));

  return (
    <section>
      <StepHeader
        step="s6"
        title="Timeline Spec"
        desc="영상 엔진에 그대로 넣는 기계용 지시서. 경로·길이는 규칙으로 정하고(실제 음성 길이 + 여백), LLM은 장면별 모션·전환·자막 스타일만 고른다."
        right={
          <div className="flex flex-col items-end gap-2">
            <span className="text-[12px] text-faint">합성 엔진</span>
            <div className="w-[300px] max-w-full">
              <Seg label="합성 엔진" value="ffmpeg" onChange={() => {}} options={ENGINES} />
            </div>
          </div>
        }
      />
      {!tl ? (
        <p className="rounded-[14px] border border-dashed border-line-dash bg-surface p-8 text-center text-muted">
          아직 지시서를 만들지 않았다.
        </p>
      ) : (
        <>
          {/* 장면 길이 트랙 */}
          <div className="mb-1.5 flex h-11 gap-[3px]" aria-label="장면별 길이">
            {tl.scenes.map((s) => {
              const role = roleOf[s.id];
              const d = typeof s.duration === "number" ? s.duration : 3;
              return (
                <div
                  key={s.id}
                  className="relative flex min-w-0 items-center overflow-hidden rounded-[5px] px-2.5 text-[12px] font-semibold whitespace-nowrap text-canvas"
                  style={{
                    flex: d,
                    background: role ? ROLE_COLOR[role] : "var(--color-ink-2)",
                  }}
                  title={`${s.id} ${role ? ROLE_LABEL[role] : ""} · ${d.toFixed(2)}s · ${s.motion.type} · ${s.transition.type}`}
                >
                  {s.id}
                  <span className="ml-1.5 font-mono text-[10.5px] font-medium opacity-70">{d.toFixed(1)}s</span>
                </div>
              );
            })}
          </div>
          <div className="mb-6 flex justify-between font-mono text-[10.5px] text-faint">
            {[0, 1, 2, 3].map((k) => (
              <span key={k}>{((total * k) / 3).toFixed(0)}s</span>
            ))}
          </div>

          <Panel title="렌더 전 미리보기" aside="BGM·어절 자막 없이 흐름만" className="mb-4">
            <TimelinePreview projectId={project.id} timeline={tl} version={project.version} />
          </Panel>

          <div className="overflow-x-auto rounded-[14px] border border-line bg-surface">
            <table className="w-full min-w-[640px] border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-line text-left text-[11.5px] whitespace-nowrap text-muted">
                  {["장면", "길이", "모션", "전환", "자막", "텍스트"].map((h) => (
                    <th key={h} className="px-4 py-[11px] font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tl.scenes.map((s) => (
                  <tr key={s.id} className="border-b border-line transition-colors last:border-0 hover:bg-white/[.02]">
                    <td className="px-4 py-3 font-semibold">
                      <span className="flex items-center gap-2">
                        <i
                          className="size-2 rounded-[2px]"
                          style={{
                            background: roleOf[s.id] ? ROLE_COLOR[roleOf[s.id]] : "var(--color-faint)",
                          }}
                        />
                        {s.id}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <Mono className="text-ink-2">
                        {typeof s.duration === "number" ? `${s.duration.toFixed(2)}s` : "auto"}
                      </Mono>
                    </td>
                    <td className="px-4 py-3">
                      <Mono className="text-ink-2">
                        {s.motion.type} {s.motion.amount}
                      </Mono>
                    </td>
                    <td className="px-4 py-3">
                      <Mono className="text-ink-2">
                        {s.transition.type}
                        {s.transition.type !== "cut" && ` ${s.transition.dur}s`}
                      </Mono>
                    </td>
                    <td className="px-4 py-3">
                      <Mono className="text-ink-2">{s.caption.style}</Mono>
                    </td>
                    <td className="max-w-[280px] truncate px-4 py-3 text-muted">{s.caption.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 mb-2.5 flex flex-wrap items-center justify-between gap-3">
            <span className="flex items-center gap-3">
              <Mono className="text-muted">timeline.json</Mono>
              <span className="inline-flex items-center gap-1.5 text-[12px] text-ok">
                <svg
                  viewBox="0 0 16 16"
                  width="14"
                  height="14"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M3.5 8.5l3 3 6-7" />
                </svg>
                스키마 검증 통과
              </span>
            </span>
            <span className="flex items-center gap-3 text-[12.5px] text-muted">
              합계 <Mono className="text-ink">{total.toFixed(2)}s</Mono> · {tl.canvas.w}×{tl.canvas.h} · {tl.canvas.fps}
              fps · 자막 {tl.subtitles.source === "tts" ? "TTS 어절 타이밍" : "Whisper"}
              <button type="button" className="text-accent hover:underline" onClick={() => setRaw(!raw)}>
                {raw ? "JSON 접기" : "JSON 보기"}
              </button>
            </span>
          </div>
          {raw && (
            <pre className="max-h-[460px] overflow-auto rounded-[14px] border border-line bg-sunken px-[22px] py-5 font-mono text-[12.5px] leading-[1.75] text-ink-2">
              {JSON.stringify(tl, null, 2)
                .split("\n")
                .map((line, i) => (
                  <span key={i} className="block">
                    <span className="mr-4 inline-block w-[2.2em] text-right text-faint select-none">{i + 1}</span>
                    <span dangerouslySetInnerHTML={{ __html: highlight(line) }} />
                  </span>
                ))}
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
