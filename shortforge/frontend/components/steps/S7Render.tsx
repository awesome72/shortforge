"use client";

import { fileUrl } from "@/lib/api";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Button, Card, Mono } from "../ui";

const STAGES = [
  { id: "clips", label: "장면 클립 (병렬 인코딩)" },
  { id: "compose", label: "합성 · 자막 번인 · 인코딩" },
];

export function S7Render({ project, controls, progress, setTab }: StepProps) {
  const r = project.render;
  const done = project.status.s7 === "done" && r;
  const running = project.status.s7 === "running";
  const video = done ? fileUrl(project.id, r.path, project.version) : null;
  const srt = done ? fileUrl(project.id, r.srt, project.version, true) : null;
  const mp4Download = done ? fileUrl(project.id, r.path, project.version, true) : null;
  const log = done ? fileUrl(project.id, r.log, project.version) : null;
  const stageIdx = progress ? STAGES.findIndex((s) => progress.stage.startsWith(s.id)) : -1;

  return (
    <section>
      <StepHeader
        step="s7"
        title="렌더 결과"
        desc="FFmpeg로 장면 클립 → 전환 → 음성 배치 → 자막 번인 → H.264/AAC. CPU만으로 30초 영상 약 50초."
      />
      <div className="flex flex-wrap gap-6">
        <div className="flex-none">
          {video ? (
            <video
              key={video}
              src={video}
              controls
              playsInline
              className="aspect-[9/16] w-[270px] rounded-xl border border-line bg-ink"
            />
          ) : (
            <div className="flex aspect-[9/16] w-[270px] items-center justify-center rounded-xl border border-line bg-ink p-6 text-center text-[13px] text-muted-2">
              {running ? "렌더 중…" : project.status.s7 === "stale" ? "앞 단계가 바뀌었다 — 다시 렌더" : "아직 렌더하지 않았다"}
            </div>
          )}
        </div>
        <div className="flex min-w-[240px] flex-1 flex-col gap-3">
          <Card>
            <div className="mb-2 text-[12px] font-medium text-muted">진행</div>
            {STAGES.map((s, i) => {
              const state = done ? "완료" : running ? (i < stageIdx ? "완료" : i === stageIdx ? `${Math.round((progress?.progress ?? 0) * 100)}%` : "대기") : "대기";
              return (
                <div key={s.id} className="flex justify-between border-b border-line py-1.5 text-[13px] last:border-0">
                  <span>{s.label}</span>
                  <Mono className={state === "완료" ? "text-ok" : "text-muted"}>{state}</Mono>
                </div>
              );
            })}
          </Card>
          {done && (
            <Card>
              <div className="text-[13px]">
                길이 <Mono>{r.duration_sec.toFixed(2)}초</Mono> · 1080×1920
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <a
                  href={mp4Download ?? "#"}
                  className="inline-flex min-h-11 items-center rounded-lg bg-accent px-4 font-semibold text-white no-underline hover:bg-accent-strong hover:text-white"
                >
                  MP4 다운로드 (1080×1920)
                </a>
                <a
                  href={srt ?? "#"}
                  className="inline-flex min-h-11 items-center rounded-lg border border-line-strong bg-card px-4 font-semibold text-ink no-underline hover:bg-surface hover:text-ink"
                >
                  SRT 자막
                </a>
              </div>
              {log && (
                <a href={log} target="_blank" rel="noreferrer" className="mt-2 inline-block text-[12px]">
                  render.log 보기
                </a>
              )}
            </Card>
          )}
          <Button variant="ghost" onClick={() => setTab("s4")}>
            전략으로 돌아가 A/B 버전 만들기
          </Button>
          <p className="text-[12px] text-muted">
            지금은 같은 프로젝트에서 대사·제목을 고쳐 다시 렌더한다. 프로젝트 복제(A/B 변형 보관)는 M2(F-W6)에서
            추가한다.
          </p>
        </div>
      </div>
      <StepActions
        project={project}
        step="s7"
        controls={controls}
        progress={progress}
        primaryLabel={done ? "다시 렌더 (S7 실행)" : "렌더링 (S7 실행)"}
      />
    </section>
  );
}
