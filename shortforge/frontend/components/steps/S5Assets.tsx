"use client";

import { api, fileUrl } from "@/lib/api";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Button, Card, Mono } from "../ui";

export function S5Assets({ project, controls, save, guard, progress }: StepProps) {
  const assets = project.assets ?? [];
  const scenes = Object.fromEntries((project.strategy?.scenes ?? []).map((s) => [s.id, s]));

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
      "세로 9:16(예: 768×1344) 이미지를 장면 순서대로 만든 뒤, 5단계에서 장면별 \"사진 교체\"로 올린다.",
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
        desc="스타일 시드(공통 접미사)와 고정 seed로 장면 간 톤을 맞춘다. 이미지는 본인 사진이 기본(GPU 없음), 음성은 Edge-TTS로 바로 만든다. 사진을 바꾸면 6단계부터 재생성 필요."
      />
      {project.strategy && (
        <div className="mb-3.5 flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1 rounded-lg border border-line bg-card px-3 py-2 font-mono text-[12px] text-ink-2">
            STYLE_SEED: {project.strategy.style_seed}
          </div>
          {assets.length > 0 && (
            <Button variant="ghost" onClick={exportPrompts}>
              이미지 프롬프트 내보내기 (.md)
            </Button>
          )}
        </div>
      )}
      {assets.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line-dash bg-surface p-6 text-center text-muted">
          아직 자산을 만들지 않았다. 1단계에서 사진을 올려 두면 장면 순서대로 쓰인다.
        </p>
      ) : (
        <div className="flex flex-col gap-2.5">
          {assets.map((a) => {
            const img = fileUrl(project.id, a.image.path, project.version);
            const voice = fileUrl(project.id, a.voice.path, project.version);
            return (
              <Card key={a.scene_id} className="flex flex-wrap gap-4">
                <div className="flex w-[90px] flex-none flex-col items-center gap-1.5">
                  {img ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={img} alt="" className="h-[160px] w-[90px] rounded-md border border-line object-cover" />
                  ) : (
                    <div className="flex h-[160px] w-[90px] items-center justify-center rounded-md border border-dashed border-line-dash bg-surface p-1 text-center text-[11px] text-muted">
                      {a.image.path ? a.image.path.split(/[\\/]/).pop() : "사진 없음"}
                    </div>
                  )}
                  <label className="cursor-pointer text-[12px] text-accent hover:underline">
                    사진 교체
                    <input
                      type="file"
                      accept=".jpg,.jpeg,.png,.webp"
                      className="sr-only"
                      disabled={project.busy}
                      onChange={(e) => replacePhoto(a.scene_id, e.target.files?.[0])}
                    />
                  </label>
                </div>
                <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-2">
                  <div className="text-[13px] font-semibold">
                    {a.scene_id} · 이미지 {a.image.source === "user" ? "(본인 사진)" : "(생성 프롬프트)"}
                  </div>
                  <div className="rounded-md bg-surface px-2.5 py-1.5 font-mono text-[12px] text-ink-2">
                    {a.image.prompt}
                    <span className="text-muted"> · seed={a.image.seed}</span>
                  </div>
                  <div className="text-[13px] font-semibold">
                    {a.scene_id} · 음성 (Edge-TTS {a.voice.voice.replace("ko-KR-", "").replace("Neural", "")}
                    {a.voice.rate !== "+0%" && ` · 속도 ${a.voice.rate}`})
                  </div>
                  <div className="text-[14px]">{a.voice.text}</div>
                  {scenes[a.scene_id] && scenes[a.scene_id].line.trim() !== a.voice.text.replace(/\.$/, "") && (
                    <div className="text-[12px] text-muted">원래 대사: {scenes[a.scene_id].line}</div>
                  )}
                  <div className="flex flex-wrap items-center gap-3">
                    {voice && <audio controls preload="none" src={voice} className="h-9 max-w-full" />}
                    {a.voice.duration_sec !== null && <Mono className="text-muted">{a.voice.duration_sec.toFixed(2)}초</Mono>}
                  </div>
                </div>
              </Card>
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
