"use client";

import { EVIDENCE_LABEL, FACTOR_LABEL } from "@/lib/labels";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Details, Notice } from "../ui";

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

/** 근거는 "근거 영상 N개"로 접어 두고, 펼치면 영상별로 어떤 항목을 봤는지 보여 준다 */
function Evidence({
  evidence,
  titles,
  thumbs,
}: {
  evidence: string[];
  titles: Record<string, string>;
  thumbs: Record<string, string>;
}) {
  const byVideo = new Map<string, string[]>();
  for (const e of evidence) {
    const [vid, field] = e.split(":");
    byVideo.set(vid, [...(byVideo.get(vid) ?? []), field]);
  }
  const vids = [...byVideo.keys()];
  return (
    <Details
      className="mt-auto border-t border-line pt-2.5"
      summary={
        <span className="flex items-center gap-2">
          근거 영상 {vids.length}개
          <span className="flex -space-x-1" aria-hidden="true">
            {vids.slice(0, 4).map((v) =>
              thumbs[v] ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={v}
                  src={thumbs[v]}
                  alt=""
                  className="h-5 w-[11px] rounded-[2px] object-cover ring-1 ring-surface"
                />
              ) : null,
            )}
          </span>
        </span>
      }
    >
      <div className="flex flex-col gap-1.5">
        {vids.map((v) => (
          <div key={v} className="flex items-baseline gap-2 text-[12px]" title={titles[v] ?? v}>
            <span className="line-clamp-1 min-w-0 flex-1 text-ink-2">{titles[v] ?? v}</span>
            <span className="flex-none text-faint">
              {byVideo
                .get(v)!
                .map((f) => EVIDENCE_LABEL[f] ?? f)
                .join(" · ")}
            </span>
          </div>
        ))}
      </div>
    </Details>
  );
}

export function S3Factors({ project, controls, progress, config }: StepProps) {
  const factors = project.factors ?? [];
  const confirmed = factors.filter((f) => f.confidence === "confirmed").length;
  const titles = Object.fromEntries((project.refs ?? []).map((r) => [r.video_id, r.title]));
  const thumbs = Object.fromEntries((project.refs ?? []).map((r) => [r.video_id, r.thumbnail_url]));

  return (
    <section>
      <StepHeader
        step="s3"
        title="왜 이 영상들이 터졌나"
        desc="고른 영상의 제목·길이·게시 시각·통계·댓글·썸네일을 보고 잘 된 이유를 정리해요. 근거가 없는 요인은 빼요."
        tech={
          <>
            YouTube API는 다른 채널의 시청 지속률과 유입 경로를 주지 않아요. 그래서 훅과 화면 구성은 늘 ‘추정’으로
            표시해요. 썸네일은 내려받지 않고 주소만 모델에 넘겨요(이미지를 못 보는 Ollama 같은 모델이면 건너뛰어요).
            요인마다 근거가 된 영상과 항목이 붙고, 고르지 않은 영상을 가리키는 근거는 지워요.
          </>
        }
        right={
          factors.length > 0 ? (
            <div className="flex gap-2">
              <span className="rounded-full bg-ok-tint px-2.5 py-1 text-[12px] font-semibold text-ok">
                확인 {confirmed}
              </span>
              <span className="rounded-full px-2.5 py-1 text-[12px] font-semibold text-stale shadow-[inset_0_0_0_1px_var(--color-stale-line)]">
                추정 {factors.length - confirmed}
              </span>
            </div>
          ) : undefined
        }
      />
      {factors.length === 0 ? (
        <p className="rounded-[14px] border border-dashed border-line-dash bg-surface p-8 text-center text-muted">
          아직 분석하지 않았어요.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-px overflow-hidden rounded-[14px] border border-line bg-line md:grid-cols-2 2xl:grid-cols-3">
          {factors.map((f, i) => (
            <article
              key={`${f.name}-${i}`}
              className="flex min-h-[168px] flex-col gap-2.5 bg-surface px-5 pt-5 pb-[18px]"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[12.5px] font-medium text-muted">{FACTOR_LABEL[f.name]}</span>
                <Confidence confirmed={f.confidence === "confirmed"} />
              </div>
              <p className="text-[15px] leading-[1.55] font-semibold tracking-[-0.015em] text-ink">{f.finding}</p>
              <Evidence evidence={f.evidence} titles={titles} thumbs={thumbs} />
            </article>
          ))}
        </div>
      )}
      {factors.length > 0 && factors.length > confirmed && (
        <div className="mt-4">
          <Notice tone="info">
            ‘추정’은 공개 데이터로 확인할 수 없어 모델이 짐작한 내용이에요. 그대로 따르기보다 참고로 봐 주세요.
          </Notice>
        </div>
      )}
      <StepActions
        project={project}
        step="s3"
        controls={controls}
        progress={progress}
        advanced={config?.advanced}
        primaryLabel={factors.length ? "다시 분석" : "성공 요인 분석"}
        next="s4"
      />
    </section>
  );
}
