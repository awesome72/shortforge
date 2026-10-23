"use client";

import { fmtNum } from "@/lib/labels";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Mono } from "../ui";

export function S2Refs({ project, controls, save, progress }: StepProps) {
  const refs = project.refs ?? [];
  const selected = refs.filter((r) => r.selected).length;

  const toggle = (videoId: string) =>
    save(
      "refs",
      refs.map((r) => (r.video_id === videoId ? { ...r, selected: !r.selected } : r)),
    );

  // 구독자 대비 배수 막대의 기준값. 극단값 하나가 나머지를 다 0으로 만들지 않게 2번째로 큰 값의 2배로 자른다
  const ratios = (project.refs ?? []).map((r) => r.ratio_views_per_sub ?? 0).sort((a, b) => b - a);
  const maxRatio = Math.max(1, Math.min(ratios[0] ?? 1, (ratios[1] ?? ratios[0] ?? 1) * 2));

  return (
    <section>
      <StepHeader
        step="s2"
        title="조회수 상위 숏폼 레퍼런스"
        desc="search.list(type=video, videoDuration=short) → videos.list로 통계 일괄 조회. 정렬은 단순 조회수가 아니라 구독자 대비 조회수와 일평균 조회수, 그리고 주제 관련성."
      />
      <div className="mb-3.5 flex flex-wrap gap-2 text-[12px]">
        {["최근 90일", "60초 이하", `regionCode=${project.input?.region ?? "KR"}`, "정렬: 구독자 대비 배수"].map(
          (c) => (
            <span key={c} className="rounded-full border border-line bg-card px-2.5 py-0.5 text-ink-2">
              {c}
            </span>
          ),
        )}
      </div>

      {refs.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line-dash bg-surface p-6 text-center text-muted">
          아직 검색하지 않았다. 키워드 3개 × 1페이지 ≈ 303 units, 같은 날 재실행은 캐시로 0 units.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-[14px] border border-line bg-surface">
          <table className="w-full min-w-[720px] border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-line text-left text-[11.5px] whitespace-nowrap text-muted [&>th]:px-4 [&>th]:py-[11px]">
                <th className="px-3 py-2 font-medium">선택</th>
                <th className="px-3 py-2 font-medium">영상</th>
                <th className="px-3 py-2 text-right font-medium">조회수</th>
                <th className="px-3 py-2 text-right font-medium text-accent">구독자 대비 ▾</th>
                <th className="px-3 py-2 text-right font-medium">일평균</th>
                <th className="px-3 py-2 text-right font-medium">좋아요율</th>
                <th className="px-3 py-2 text-right font-medium">길이</th>
              </tr>
            </thead>
            <tbody>
              {refs.map((r) => (
                <tr
                  key={r.video_id}
                  className={`border-b border-line last:border-0 ${r.relevant === false ? "opacity-55" : ""} ${r.selected ? "bg-accent-tint/50" : ""}`}
                >
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      className="size-4 accent-accent"
                      checked={r.selected}
                      disabled={project.busy}
                      onChange={() => toggle(r.video_id)}
                      aria-label={`${r.title} 선택`}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2.5">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={r.thumbnail_url}
                        alt=""
                        className="h-[52px] w-[30px] flex-none rounded bg-line object-cover"
                        referrerPolicy="no-referrer"
                      />
                      <div className="min-w-0">
                        <a
                          href={`https://www.youtube.com/shorts/${r.video_id}`}
                          target="_blank"
                          rel="noreferrer"
                          className="line-clamp-2 text-ink no-underline hover:underline"
                        >
                          {r.title}
                        </a>
                        <div className="text-[12px] text-muted">
                          구독자 {r.subs === null ? "비공개" : fmtNum(r.subs)}
                          {r.relevant === false && <span className="ml-2 text-stale">· 주제 관련성 낮음</span>}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Mono>{fmtNum(r.views)}</Mono>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex items-center justify-end gap-2.5">
                      {r.ratio_views_per_sub !== null && (
                        <span className="h-1 w-[72px] overflow-hidden rounded-full bg-line" aria-hidden="true">
                          <i
                            className="block h-full rounded-full bg-accent"
                            style={{ width: `${Math.min(100, (r.ratio_views_per_sub / maxRatio) * 100)}%` }}
                          />
                        </span>
                      )}
                      <Mono className="min-w-[52px] text-right font-semibold text-ink">
                        {r.ratio_views_per_sub === null ? "—" : `${r.ratio_views_per_sub.toFixed(1)}×`}
                      </Mono>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Mono>{fmtNum(r.views_per_day)}</Mono>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Mono>{(r.like_rate * 100).toFixed(2)}%</Mono>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Mono>{r.duration_sec}s</Mono>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <StepActions
        project={project}
        step="s2"
        controls={controls}
        progress={progress}
        primaryLabel={refs.length ? "다시 검색 (S2 실행)" : "유사 영상 검색 (S2 실행)"}
        next="s3"
      />
      {refs.length > 0 && (
        <p className="mt-3 text-[13px] text-muted">
          선택 {selected}개 → 3단계에서 분석한다. 선택을 바꾸면 3단계부터 &quot;재생성 필요&quot;가 된다.
        </p>
      )}
    </section>
  );
}
