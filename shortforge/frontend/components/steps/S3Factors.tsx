"use client";

import { FACTOR_LABEL } from "@/lib/labels";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Card, Mono } from "../ui";

export function S3Factors({ project, controls, progress }: StepProps) {
  const factors = project.factors ?? [];
  const titles = Object.fromEntries((project.refs ?? []).map((r) => [r.video_id, r.title]));
  const thumbs = Object.fromEntries((project.refs ?? []).map((r) => [r.video_id, r.thumbnail_url]));

  return (
    <section>
      <StepHeader
        step="s3"
        title="왜 이 영상들이 터졌나"
        desc="입력: 메타데이터(제목·길이·게시시각·통계) + 상위 댓글(commentThreads) + 썸네일 관찰(Gemini가 URL로 직접 본다). 모든 요인에 근거 필드와 신뢰도를 붙이고, 근거가 없는 요인은 버린다."
      />
      {factors.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line-dash bg-surface p-6 text-center text-muted">
          아직 분석하지 않았다.
        </p>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3.5">
          {factors.map((f, i) => (
            <Card key={`${f.name}-${i}`}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-semibold">{FACTOR_LABEL[f.name]}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${f.confidence === "confirmed" ? "bg-ok-tint text-ok" : "bg-stale-tint text-stale-strong"}`}
                >
                  {f.confidence === "confirmed" ? "확인" : "추정"}
                </span>
              </div>
              <p className="mt-2 text-[14px]">{f.finding}</p>
              <div className="mt-3 flex flex-col gap-1 border-t border-line pt-2">
                {f.evidence.map((e) => {
                  const [vid, field] = e.split(":");
                  return (
                    <div key={e} className="flex items-center gap-1.5 text-[12px] text-muted" title={titles[vid] ?? vid}>
                      {field === "thumbnail" && thumbs[vid] && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={thumbs[vid]} alt="" className="h-6 w-auto flex-none rounded-sm" />
                      )}
                      <span className="flex-none">근거:</span> <Mono className="flex-none text-ink-2">{field}</Mono>{" "}
                      <span className="line-clamp-1">{titles[vid] ?? vid}</span>
                    </div>
                  );
                })}
              </div>
            </Card>
          ))}
        </div>
      )}
      <p className="mt-4 text-[13px] text-muted">
        한계: API는 타 채널의 시청 지속률(retention)·유입 경로를 주지 않는다. 훅·화면 구성은 &quot;추정&quot; 등급으로
        표시된다. 썸네일은 내려받지 않고 URL만 모델에 넘긴다(Ollama 등 이미지를 못 보는 모델이면 건너뛴다).
      </p>
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
