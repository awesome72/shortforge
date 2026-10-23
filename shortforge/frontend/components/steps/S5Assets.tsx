"use client";

import Link from "next/link";
import { useState } from "react";
import { api, fileUrl } from "@/lib/api";
import { ROLE_COLOR, ROLE_LABEL } from "@/lib/labels";
import type { Asset, ImageAsset } from "@/lib/types";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Button, Mono, Notice } from "../ui";

const SOURCE_BADGE: Record<Asset["image"]["source"], { label: string; cls: string }> = {
  user: { label: "본인 사진", cls: "bg-ok-tint text-ok" },
  generated: { label: "AI 생성", cls: "bg-accent-tint text-accent" },
  stock: { label: "무료 사진", cls: "bg-[rgba(126,156,216,.14)] text-role-problem" },
};

function Credit({ credit }: { credit: string }) {
  const [text, url] = credit.split(" · ");
  return url ? (
    <a href={url} target="_blank" rel="noreferrer" className="text-[11px] text-muted hover:text-accent">
      {text}
    </a>
  ) : (
    <span className="text-[11px] text-muted">{text}</span>
  );
}

export function S5Assets({ project, controls, save, guard, progress, config }: StepProps) {
  const assets = project.assets ?? [];
  const canGenerate = (config?.image_sources.length ?? 0) > 0;
  const missing = assets.filter((a) => !a.image.path).map((a) => a.scene_id);
  const [busyScene, setBusyScene] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[]>([]);

  const regenerate = (sceneId: string) =>
    guard(async () => {
      setBusyScene(sceneId);
      try {
        const r = await api.regenerateImage(project.id, sceneId); // 결과는 SSE(edited)로 반영된다
        setNotices(r.notices);
      } finally {
        setBusyScene(null);
      }
    });
  const scenes = Object.fromEntries((project.strategy?.scenes ?? []).map((s) => [s.id, s]));

  // 후보 3개 중 고르기 (F-5.4): 만든 후보는 적용 전까지 화면에만 둔다
  const [candidates, setCandidates] = useState<Record<string, ImageAsset[]>>({});
  const loadCandidates = (sceneId: string) =>
    guard(async () => {
      setBusyScene(sceneId);
      try {
        const r = await api.candidates(project.id, sceneId);
        setCandidates((c) => ({ ...c, [sceneId]: r.candidates }));
        setNotices(r.notices);
      } finally {
        setBusyScene(null);
      }
    });
  const choose = (sceneId: string, cand: ImageAsset) =>
    guard(async () => {
      await api.selectCandidate(project.id, sceneId, cand); // 화면은 SSE(edited)로 갱신된다
      setCandidates((c) => {
        const next = { ...c };
        delete next[sceneId];
        return next;
      });
    });

  const replacePhoto = (sceneId: string, file: File | undefined) => {
    if (!file) return;
    guard(async () => {
      const { saved } = await api.upload(project.id, [file], false); // input은 건드리지 않는다
      await save(
        "assets",
        assets.map((a) =>
          a.scene_id === sceneId ? { ...a, image: { ...a.image, source: "user" as const, path: saved[0] } } : a,
        ),
      );
    });
  };

  // 기본 경로(D4): GPU가 없으면 프롬프트를 내보내 외부 무료 도구로 만든 뒤 "사진 교체"로 올린다
  const exportPrompts = () => {
    const s = project.strategy;
    const lines = [
      `# ShortForge 이미지 프롬프트 — ${project.input?.topic ?? ""}`,
      "",
      '세로 9:16(예: 768×1344) 이미지를 장면 순서대로 만든 뒤, 5단계에서 장면별 "사진 교체"로 올린다.',
      "",
      `- 스타일 시드(공통): ${s?.style_seed ?? ""}`,
      `- negative(공통): ${assets[0]?.image.negative ?? ""}`,
      `- seed(공통, 장면 간 일관성): ${assets[0]?.image.seed ?? ""}`,
      "",
      ...assets.flatMap((a) => [
        `## ${a.scene_id} · ${scenes[a.scene_id]?.role ?? ""} (${scenes[a.scene_id]?.start ?? ""}–${scenes[a.scene_id]?.end ?? ""}초)`,
        "",
        `- 프롬프트: ${a.image.prompt}`,
        `- 대사: ${a.voice.text}`,
        "",
      ]),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `shortforge_${project.id}_prompts.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section>
      <StepHeader
        step="s5"
        title="장면별 자산"
        desc="이미지는 본인 사진 → 무료 AI 생성(Cloudflare) → 무료 사진(Pixabay) 순서로 채운다. 스타일 시드와 고정 seed로 장면 간 톤을 맞춘다. 다시 실행해도 장면 묘사가 그대로인 장면은 지금 이미지(고른 후보·교체한 사진 포함)를 유지한다. 사진을 바꾸면 6단계부터 재생성 필요."
      />
      {notices.length > 0 && (
        <div className="mb-3">
          <Notice tone="warn">
            {notices.map((n) => (
              <div key={n}>· {n}</div>
            ))}
          </Notice>
        </div>
      )}
      {project.strategy && (
        <div className="mb-3.5 flex flex-wrap items-center gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-3.5 overflow-x-auto rounded-[10px] border border-line bg-sunken px-4 py-3 text-[13px] text-ink-2">
            <span className="flex-none font-mono text-[12px] text-accent">STYLE_SEED</span>
            <span className="min-w-0 flex-1">{project.strategy.style_seed}</span>
            <span className="flex-none text-[11.5px] text-muted">모든 장면 공통</span>
          </div>
          {assets.length > 0 && (
            <Button variant="ghost" onClick={exportPrompts}>
              이미지 프롬프트 내보내기 (.md)
            </Button>
          )}
        </div>
      )}
      {missing.length > 0 && project.status.s5 !== "running" && (
        <div className="mb-4 rounded-lg border border-stale-line bg-stale-tint px-4 py-3 text-[13px] text-stale-strong">
          <div className="font-semibold">
            이미지가 없는 장면 {missing.length}개 ({missing.join(", ")}) — 이대로는 6단계를 실행할 수 없다
          </div>
          <p className="mt-1">{project.not_ready?.s6 ?? "장면 카드의 '사진 교체'로 사진을 올린다."}</p>
          <div className="mt-2.5 flex flex-wrap gap-2">
            <Link
              href="/settings"
              className="inline-flex min-h-9 items-center rounded-lg border border-line-strong bg-card px-3 font-semibold text-ink no-underline hover:bg-surface"
            >
              설정에서 이미지 방식 바꾸기
            </Link>
            <Button variant="ghost" className="min-h-9" disabled={project.busy} onClick={() => controls.run("s5")}>
              5단계 다시 실행 (지금 설정으로)
            </Button>
            <Button variant="ghost" className="min-h-9" onClick={exportPrompts}>
              프롬프트 내보내기 (직접 만들어 올리기)
            </Button>
          </div>
        </div>
      )}
      {assets.length === 0 ? (
        <p className="rounded-[14px] border border-dashed border-line-dash bg-surface p-8 text-center text-muted">
          아직 자산을 만들지 않았다. 1단계에서 사진을 올려 두면 장면 순서대로 쓰인다.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {assets.map((a) => {
            const img = fileUrl(project.id, a.image.path, project.version);
            const voice = fileUrl(project.id, a.voice.path, project.version);
            const scene = scenes[a.scene_id];
            const action =
              "text-left text-[12px] text-ink-2 hover:text-accent disabled:cursor-not-allowed disabled:text-faint";
            return (
              <article key={a.scene_id} className="overflow-hidden rounded-[14px] border border-line bg-surface">
                <div className="grid grid-cols-1 md:grid-cols-[124px_minmax(0,1.15fr)_minmax(0,1fr)]">
                  {/* 썸네일·이미지 작업 */}
                  <div className="flex gap-3 p-4 md:flex-col">
                    {img ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={img}
                        alt=""
                        className="aspect-[9/16] w-[92px] flex-none rounded-md border border-line-strong object-cover"
                      />
                    ) : (
                      <div className="flex aspect-[9/16] w-[92px] flex-none items-center justify-center rounded-md border border-dashed border-stale-line bg-stale-tint p-1 text-center text-[11px] text-stale">
                        {a.image.path ? a.image.path.split(/[\\/]/).pop() : "이미지 없음"}
                      </div>
                    )}
                    <div className="flex flex-col gap-1.5">
                      <label className={`cursor-pointer ${action}`}>
                        사진 교체
                        <input
                          type="file"
                          accept=".jpg,.jpeg,.png,.webp"
                          className="sr-only"
                          disabled={project.busy}
                          onChange={(e) => replacePhoto(a.scene_id, e.target.files?.[0])}
                        />
                      </label>
                      {canGenerate && (
                        <button
                          type="button"
                          className={action}
                          disabled={project.busy || busyScene !== null}
                          onClick={() => regenerate(a.scene_id)}
                        >
                          {busyScene === a.scene_id ? "만드는 중…" : "다른 이미지"}
                        </button>
                      )}
                      {canGenerate && (
                        <button
                          type="button"
                          className={action}
                          disabled={project.busy || busyScene !== null}
                          onClick={() => loadCandidates(a.scene_id)}
                          title="seed를 바꾼 후보 3장을 만든다 (Cloudflare 약 470 Neurons)"
                        >
                          후보 3개
                        </button>
                      )}
                    </div>
                  </div>

                  {/* 이미지 프롬프트 */}
                  <div className="min-w-0 border-t border-line p-4 md:border-t-0 md:border-l">
                    <div className="mb-2.5 flex flex-wrap items-center gap-2 text-[12px] text-muted">
                      {scene && (
                        <i className="size-2 flex-none rounded-[2px]" style={{ background: ROLE_COLOR[scene.role] }} />
                      )}
                      <b className="text-[13px] font-semibold text-ink">{a.scene_id}</b>
                      {scene ? ROLE_LABEL[scene.role] : ""} · 이미지
                      {a.image.path && (
                        <span
                          className={`ml-auto rounded px-1.5 py-0.5 text-[11px] font-medium ${SOURCE_BADGE[a.image.source].cls}`}
                          title={a.image.provider ?? ""}
                        >
                          {SOURCE_BADGE[a.image.source].label}
                          {a.image.source === "generated" &&
                            a.image.provider &&
                            ` · ${a.image.provider.split(":").pop()}`}
                        </span>
                      )}
                    </div>
                    <p className="font-mono text-[12px] leading-[1.7] text-ink-2">{a.image.prompt}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-[11px] text-faint">
                      seed={a.image.seed}
                      {a.image.credit && <Credit credit={a.image.credit} />}
                    </div>
                  </div>

                  {/* 음성 */}
                  <div className="min-w-0 border-t border-line p-4 md:border-t-0 md:border-l">
                    <div className="mb-2.5 flex items-center gap-2 text-[12px] text-muted">
                      <b className="text-[13px] font-semibold text-ink">{a.scene_id}</b> 음성
                      <span className="ml-auto rounded border border-line-strong px-1.5 py-0.5 font-mono text-[10.5px] text-muted">
                        Edge-TTS {a.voice.voice.replace("ko-KR-", "").replace("Neural", "")}
                      </span>
                    </div>
                    <p className="text-[15px] font-medium tracking-[-0.01em]">{a.voice.text}</p>
                    {scene && scene.line.trim() !== a.voice.text.replace(/\.$/, "") && (
                      <p className="mt-1 text-[12px] text-muted">원래 대사: {scene.line}</p>
                    )}
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      {voice && <audio controls preload="none" src={voice} className="h-9 max-w-full" />}
                    </div>
                    <div className="mt-2 font-mono text-[11px] text-muted">
                      {a.voice.duration_sec !== null && `${a.voice.duration_sec.toFixed(2)}s`}
                      {a.voice.rate !== "+0%" && ` · rate=${a.voice.rate}`}
                    </div>
                  </div>
                </div>

                {candidates[a.scene_id] && (
                  <div className="border-t border-line bg-sunken p-4">
                    <div className="mb-3 flex items-center justify-between text-[12px] text-muted">
                      <span>후보 중 하나를 고르면 이 장면에 적용된다 (6단계부터 재생성 필요)</span>
                      <button
                        type="button"
                        className="text-muted hover:text-ink"
                        onClick={() =>
                          setCandidates((c) => {
                            const next = { ...c };
                            delete next[a.scene_id];
                            return next;
                          })
                        }
                      >
                        닫기
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-3">
                      {candidates[a.scene_id].map((c) => {
                        const url = fileUrl(project.id, c.path);
                        return (
                          <div key={c.seed} className="flex flex-col items-center gap-1.5">
                            {url && (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={url}
                                alt=""
                                className="aspect-[9/16] w-[92px] rounded-md border border-line-strong object-cover"
                              />
                            )}
                            <Mono className="text-[11px] text-faint">seed {c.seed}</Mono>
                            <Button
                              className="min-h-8 px-3 text-[12px]"
                              disabled={project.busy}
                              onClick={() => choose(a.scene_id, c)}
                            >
                              이걸로
                            </Button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
      <StepActions
        project={project}
        step="s5"
        controls={controls}
        progress={progress}
        primaryLabel={assets.length ? "자산 다시 만들기 (S5 실행)" : "로컬에서 자산 생성 (S5 실행)"}
        next="s6"
      />
    </section>
  );
}
