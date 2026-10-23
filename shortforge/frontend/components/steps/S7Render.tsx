"use client";

import { useRouter } from "next/navigation";
import { api, fileUrl } from "@/lib/api";
import { VideoPlayer } from "../Media";
import { PublishChecklist } from "../PublishChecklist";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Button, Panel } from "../ui";

// 렌더 어댑터가 보내는 진행 단계(progress.stage)와 화면 표시
const STAGES = [
  { id: "spec", label: "편집 지시서 확인" },
  { id: "clips", label: "장면별 클립 만들기" },
  { id: "compose", label: "전환 · 음성 · 자막 합치기" },
  { id: "encode", label: "최종 영상 인코딩" },
];

type RowState = "done" | "run" | "wait";

function StageIcon({ state }: { state: RowState }) {
  if (state === "done")
    return (
      <svg
        viewBox="0 0 16 16"
        width="14"
        height="14"
        className="text-ok"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M3.5 8.5l3 3 6-7" />
      </svg>
    );
  if (state === "run")
    return (
      <svg viewBox="0 0 16 16" width="14" height="14" className="sf-pulse text-accent" aria-hidden="true">
        <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.5" opacity=".35" />
        <path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor" />
      </svg>
    );
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" className="text-faint" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2 2" />
    </svg>
  );
}

const DownloadIcon = () => (
  <svg
    viewBox="0 0 16 16"
    width="15"
    height="15"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M8 2.5v8M4.8 7.5L8 10.7l3.2-3.2M3 13.5h10" />
  </svg>
);

export function S7Render({ project, controls, progress, setTab, guard }: StepProps) {
  const router = useRouter();
  const r = project.render;
  const done = project.status.s7 === "done" && r;
  const running = project.status.s7 === "running";
  const video = done ? fileUrl(project.id, r.path, project.version) : null;
  const srt = done ? fileUrl(project.id, r.srt, project.version, true) : null;
  const mp4Download = done ? fileUrl(project.id, r.path, project.version, true) : null;
  const log = done ? fileUrl(project.id, r.log, project.version) : null;
  const tl = project.timeline;

  // 진행 중인 단계: clips → compose(합성·인코딩을 한 번에 한다). 스펙 검증은 시작하면 끝난 상태
  const live = progress?.stage.startsWith("compose") ? 2 : progress?.stage.startsWith("clips") ? 1 : running ? 1 : -1;
  const rowState = (i: number): RowState => {
    if (done) return "done";
    if (!running) return "wait";
    if (i === 0 || i < live) return "done";
    if (i === live || (live === 2 && i === 3)) return "run";
    return "wait";
  };
  const doneCount = STAGES.filter((_, i) => rowState(i) === "done").length;

  return (
    <section>
      <StepHeader
        step="s7"
        title="렌더 결과"
        desc="장면과 음성, 자막을 하나의 영상으로 합쳐요. 30초 영상이면 보통 1분 안에 끝나요."
        tech={
          <>
            장면별 클립을 CPU 코어 절반으로 동시에 만들고(바뀌지 않은 클립은 다시 쓰고), FFmpeg 한 번으로
            전환·음성·배경음·자막을 합쳐 H.264 MP4로 인코딩해요. 소리는 −14 LUFS로 맞춰요. 자세한 기록은 render.log에
            남아요.
          </>
        }
      />
      <div className="flex flex-wrap gap-5">
        <div className="flex-none">
          {video ? (
            <VideoPlayer
              key={video}
              src={video}
              className="aspect-[9/16] w-[270px] rounded-2xl border border-line-strong shadow-[0_30px_60px_-30px_rgba(0,0,0,.8)]"
            />
          ) : (
            <div className="flex aspect-[9/16] w-[270px] flex-col items-center justify-center gap-3 rounded-2xl border border-line-strong bg-[radial-gradient(120%_80%_at_30%_15%,#3a3428_0%,#1b1a18_45%,#0c0d10_100%)] p-6 text-center text-[13px] text-muted">
              {running && <span className="sf-pulse size-2 rounded-full bg-accent" />}
              {running
                ? "렌더 중…"
                : project.status.s7 === "stale"
                  ? "앞 단계가 바뀌었어요 — 다시 렌더해 주세요"
                  : "아직 렌더하지 않았어요"}
            </div>
          )}
        </div>

        <div className="grid min-w-[260px] flex-1 grid-cols-1 items-start gap-5 2xl:grid-cols-[minmax(0,1fr)_260px]">
          <Panel title="렌더 파이프라인" aside={`${doneCount} / ${STAGES.length}`} bodyClassName="">
            {STAGES.map((s, i) => {
              const st = rowState(i);
              return (
                <div
                  key={s.id}
                  className={`grid grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-3 px-[18px] py-3.5 ${i > 0 ? "border-t border-line" : ""}`}
                >
                  <span className="grid size-[18px] place-items-center">
                    <StageIcon state={st} />
                  </span>
                  <span className={`text-[13.5px] ${st === "wait" ? "text-muted" : ""}`}>{s.label}</span>
                  <span
                    className={`text-[12px] tabular-nums ${st === "done" ? "text-ok" : st === "run" ? "text-accent" : "text-faint"}`}
                  >
                    {st === "done"
                      ? "완료"
                      : st === "run"
                        ? `진행 중 ${Math.round((progress?.progress ?? 0) * 100)}%`
                        : "대기"}
                  </span>
                  {st === "run" && (
                    <div className="col-start-2 col-end-4 -mt-0.5 h-[3px] overflow-hidden rounded-full bg-line">
                      <i
                        className="block h-full rounded-full bg-accent transition-[width] duration-500"
                        style={{
                          width: `${Math.round((progress?.progress ?? 0) * 100)}%`,
                        }}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </Panel>

          <div className="rounded-[14px] border border-line bg-surface p-[18px]">
            <dl className="grid">
              {[
                ["해상도", tl ? `${tl.canvas.w}×${tl.canvas.h}` : "1080×1920"],
                ["길이", done ? `${r.duration_sec.toFixed(1)}초` : "—"],
                ["코덱", "H.264 · AAC"],
                ["프레임", `${tl?.canvas.fps ?? 30} fps`],
                ["자막", "영상에 새김 · SRT 따로"],
              ].map(([k, v], i) => (
                <div
                  key={k}
                  className={`flex justify-between gap-3 py-2.5 text-[13px] ${i > 0 ? "border-t border-line" : "pt-0"}`}
                >
                  <dt className="text-muted">{k}</dt>
                  <dd className="text-right text-[13px] tabular-nums text-ink">{v}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-4 flex flex-col gap-2">
              <a
                href={mp4Download ?? undefined}
                aria-disabled={!done}
                className={`inline-flex min-h-10 items-center gap-2 rounded-[10px] px-4 text-[13.5px] font-semibold no-underline ${done ? "bg-accent text-accent-ink hover:bg-accent-strong hover:text-accent-ink" : "pointer-events-none bg-card text-faint shadow-[inset_0_0_0_1px_var(--color-line)]"}`}
              >
                <DownloadIcon /> MP4 다운로드
                <span className="ml-auto font-mono text-[11px] font-medium opacity-70">1080×1920</span>
              </a>
              <a
                href={srt ?? undefined}
                aria-disabled={!done}
                className={`inline-flex min-h-10 items-center gap-2 rounded-[10px] border border-line-strong px-4 text-[13.5px] font-semibold text-ink no-underline hover:border-muted hover:bg-card hover:text-ink ${done ? "" : "pointer-events-none opacity-40"}`}
              >
                <DownloadIcon /> SRT 자막
              </a>
              {log && (
                <a href={log} target="_blank" rel="noreferrer" className="px-1 text-[12px] text-muted hover:text-ink">
                  렌더 기록 보기 (render.log)
                </a>
              )}
            </div>
          </div>
        </div>
      </div>

      {done && (
        <div className="mt-5">
          <PublishChecklist projectId={project.id} version={project.version} />
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-3 rounded-[14px] border border-line bg-surface px-[18px] py-4">
        <div className="min-w-[220px] flex-1">
          <div className="text-[13.5px] font-semibold">다음 버전 만들기</div>
          <p className="mt-1 text-[12.5px] text-muted">
            복제하면 1~4단계(레퍼런스·분석·전략)를 그대로 가져간 변형이 생겨요. 이 영상은 그대로 두고, 변형에서
            대사·제목을 바꿔 5단계부터 다시 만들어요.
          </p>
        </div>
        <Button variant="quiet" onClick={() => setTab("s4")}>
          이 프로젝트에서 고치기
        </Button>
        <Button
          variant="ghost"
          disabled={project.busy || !project.strategy}
          onClick={() =>
            guard(async () => {
              const b = await api.duplicate(project.id);
              router.push(`/p/${b.id}#s4`); // 변형의 전략 탭에서 대사·제목을 바꾼다
            })
          }
        >
          <svg
            viewBox="0 0 16 16"
            width="15"
            height="15"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M6.5 4L2.5 8l4 4M3 8h7.5a3 3 0 0 1 0 6H9" />
          </svg>
          A/B 버전 만들기 (복제)
        </Button>
      </div>

      <StepActions
        project={project}
        step="s7"
        controls={controls}
        progress={progress}
        primaryLabel={done ? "다시 렌더" : "영상 렌더"}
      />
    </section>
  );
}
