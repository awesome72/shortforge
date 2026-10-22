"use client";

import { FACTOR_LABEL } from "@/lib/labels";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Mono, Notice } from "../ui";

function Confidence({ confirmed }: { confirmed: boolean }) {
  return confirmed ? (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-ok-tint px-2 py-[3px] text-[11.5px] font-semibold whitespace-nowrap text-ok">
      <span className="size-1.5 rounded-full bg-current" />
      확인
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-[3px] text-[11.5px] font-semibold whitespace-nowrap text-stale shadow-[inset_0_0_0_1px_var(--color-stale-line)]">
      <span className="size-1.5 rounded-full border-[1.5px] border-dashed border-current" />
      추정
    </span>
  );
}

export function S3Factors({ project, controls, progress }: StepProps) {
  const factors = project.factors ?? [];
  const confirmed = factors.filter((f) => f.confidence === "confirmed").length;
  const titles = Object.fromEntries((project.refs ?? []).map((r) => [r.video_id, r.title]));
  const thumbs = Object.fromEntries((project.refs ?? []).map((r) => [r.video_id, r.thumbnail_url]));

  return (
    <section>
      <StepHeader
        step="s3"
        title="왜 이 영상들이 터졌나"
        desc="입력: 메타데이터(제목·길이·게시시각·통계) + 상위 댓글(commentThreads) + 썸네일 관찰(Gemini가 URL로 직접 본다). 모든 요인에 근거 필드와 신뢰도를 붙이고, 근거가 없는 요인은 버린다."
        right={
          factors.length > 0 ? (
            <div className="flex gap-2">
              <span className="rounded-full bg-ok-tint px-2.5 py-1 text-[12px] font-semibold text-ok">확인 {confirmed}</span>
              <span className="rounded-full px-2.5 py-1 text-[12px] font-semibold text-stale shadow-[inset_0_0_0_1px_var(--color-stale-line)]">
                추정 {factors.length - confirmed}
              </span>
            </div>
          ) : undefined
        }
      />
      {factors.length === 0 ? (
        <p className="rounded-[14px] border border-dashed border-line-dash bg-surface p-8 text-center text-muted">
          아직 분석하지 않았다.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-px overflow-hidden rounded-[14px] border border-line bg-line md:grid-cols-2 2xl:grid-cols-3">
          {factors.map((f, i) => (
            <article key={`${f.name}-${i}`} className="flex min-h-[168px] flex-col gap-2.5 bg-surface px-5 pt-5 pb-[18px]">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[12.5px] font-medium text-muted">{FACTOR_LABEL[f.name]}</span>
                <Confidence confirmed={f.confidence === "confirmed"} />
              </div>
              <p className="text-[15px] leading-[1.55] font-semibold tracking-[-0.015em] text-ink">{f.finding}</p>
              <div className="mt-auto flex flex-col gap-1 border-t border-line pt-2.5">
                {f.evidence.map((e) => {
                  const [vid, field] = e.split(":");
                  return (
                    <div key={e} className="flex items-center gap-1.5 text-[12px] text-muted" title={titles[vid] ?? vid}>
                      {field === "thumbnail" && thumbs[vid] && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={thumbs[vid]} alt="" className="h-6 w-auto flex-none rounded-sm" />
                      )}
                      <span className="flex-none text-faint">근거</span>
                      <Mono className="flex-none text-[11.5px] text-muted">{field}</Mono>
                      <span className="line-clamp-1 text-faint">{titles[vid] ?? vid}</span>
                    </div>
                  );
                })}
              </div>
            </article>
          ))}
        </div>
      )}
      <div className="mt-4">
        <Notice tone="warn">
          API는 다른 채널의 시청 지속률(retention)과 유입 경로를 주지 않는다. 그래서 훅과 화면 구성은 ‘추정’ 등급으로
          표시된다. 썸네일은 내려받지 않고 URL만 모델에 넘긴다(Ollama처럼 이미지를 못 보는 모델이면 건너뛴다).
        </Notice>
      </div>
      <StepActions
        project={project}
        step="s3"
        controls={controls}
        progress={progress}
        primaryLabel={factors.length ? "다시 분석 (S3 실행)" : "성공 요인 분석 (S3 실행)"}
        next="s4"
      />
    </section>
  );
}
