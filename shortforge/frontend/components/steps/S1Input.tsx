"use client";

import Link from "next/link";
import { useState } from "react";
import { api, fileUrl } from "@/lib/api";
import { TONE_LABEL, VISUAL_STYLE_LABEL, VOICE_LABEL } from "@/lib/labels";
import type { Input } from "@/lib/types";
import { SceneMedia } from "../Media";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Button, Seg, inputClass } from "../ui";

const EMPTY: Input = {
  topic: "",
  audience: "",
  tone: "empathetic",
  duration_sec: 30,
  aspect: "9:16",
  lang: "ko",
  region: "KR",
  user_media: [],
  keywords: [],
  visual_style: "auto",
  voice: "auto",
};

export function S1Input({ project, controls, save, guard, progress, config }: StepProps) {
  const saved = project.input ?? EMPTY;
  const [draft, setDraft] = useState<Input>(saved);
  const [syncedVersion, setSyncedVersion] = useState(project.version);
  const [kw, setKw] = useState("");
  const [dragging, setDragging] = useState(false);

  // 서버에서 새 버전이 오면(키워드 생성 등) 편집 중이 아닌 필드를 맞춘다
  if (project.version !== syncedVersion) {
    setSyncedVersion(project.version);
    setDraft(saved);
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const set = <K extends keyof Input>(k: K, v: Input[K]) => setDraft((d) => ({ ...d, [k]: v }));

  const upload = (files: FileList | null) => {
    const list = Array.from(files ?? []).filter((f) => /\.(jpe?g|png|webp)$/i.test(f.name));
    if (list.length) guard(() => api.upload(project.id, list));
  };
  const addKeyword = () => {
    const k = kw.trim();
    if (k && !draft.keywords.includes(k) && draft.keywords.length < 5) set("keywords", [...draft.keywords, k]);
    setKw("");
  };

  return (
    <section>
      <StepHeader
        step="s1"
        title="무엇을 만들고 싶나요?"
        desc="여기 적은 내용으로 비슷한 영상을 찾고, 대본의 방향을 정해요."
      />
      <div className="rounded-[14px] border border-line bg-surface p-[18px]">
        <div className="grid grid-cols-2 gap-x-4 gap-y-[18px] md:grid-cols-4">
          <label className="col-span-2 flex min-w-0 flex-col gap-[7px] md:col-span-4">
            <span className="text-[12.5px] font-medium text-ink-2">주제와 하고 싶은 이야기</span>
            <textarea
              className={`${inputClass} min-h-24 resize-y py-3 text-[15px] leading-relaxed`}
              rows={3}
              value={draft.topic}
              placeholder="예: 퇴근 후 10분 홈트로 3개월간 바뀐 점"
              onChange={(e) => set("topic", e.target.value)}
            />
          </label>
          <label className="col-span-2 flex min-w-0 flex-col gap-[7px]">
            <span className="text-[12.5px] font-medium text-ink-2">타깃 시청자</span>
            <input
              className={inputClass}
              value={draft.audience}
              placeholder="예: 30대 직장인"
              onChange={(e) => set("audience", e.target.value)}
            />
          </label>
          <label className="col-span-2 flex min-w-0 flex-col gap-[7px]">
            <span className="text-[12.5px] font-medium text-ink-2">언어와 지역</span>
            <select
              className={inputClass}
              value={`${draft.lang}|${draft.region}`}
              onChange={(e) => {
                const [lang, region] = e.target.value.split("|");
                setDraft((d) => ({ ...d, lang, region }));
              }}
            >
              <option value="ko|KR">한국어 · KR</option>
              <option value="en|US">English · US</option>
            </select>
          </label>
          <div className="col-span-2 flex min-w-0 flex-col gap-[7px]">
            <span className="text-[12.5px] font-medium text-ink-2">톤</span>
            <Seg
              label="톤"
              value={draft.tone}
              onChange={(v) => set("tone", v)}
              options={(Object.entries(TONE_LABEL) as [Input["tone"], string][]).map(([v, l]) => ({ value: v, label: l }))}
            />
          </div>
          <div className="col-span-2 flex min-w-0 flex-col gap-[7px]">
            <span className="text-[12.5px] font-medium text-ink-2">길이</span>
            <Seg
              label="길이"
              value={draft.duration_sec}
              onChange={(v) => set("duration_sec", v)}
              options={([30, 15, 60] as Input["duration_sec"][]).map((d) => ({ value: d, label: `${d}초` }))}
            />
          </div>
          <div className="col-span-2 flex min-w-0 flex-col gap-[7px]">
            <span className="text-[12.5px] font-medium text-ink-2">
              그림체{" "}
              <small className="ml-1.5 font-normal text-faint">
                바꾸면 5단계부터 다시 만들어요
              </small>
            </span>
            <Seg
              label="그림체"
              value={draft.visual_style ?? "auto"}
              onChange={(v) => set("visual_style", v)}
              options={(Object.entries(VISUAL_STYLE_LABEL) as [Input["visual_style"], string][]).map(([v, l]) => ({
                value: v,
                label: l,
              }))}
            />
          </div>
          <div className="col-span-2 flex min-w-0 flex-col gap-[7px]">
            <span className="text-[12.5px] font-medium text-ink-2">
              목소리{" "}
              <small className="ml-1.5 font-normal text-faint">자동이면 타깃에 맞춰요 · 그림 속 주인공도 따라가요</small>
            </span>
            <Seg
              label="목소리"
              value={draft.voice ?? "auto"}
              onChange={(v) => set("voice", v)}
              options={(Object.entries(VOICE_LABEL) as [Input["voice"], string][]).map(([v, l]) => ({
                value: v,
                label: l,
              }))}
            />
          </div>

          <div className="col-span-2 flex min-w-0 flex-col gap-[7px] md:col-span-4">
            <span className="text-[12.5px] font-medium text-ink-2">
              내 소재 <small className="ml-1.5 font-normal text-faint">선택 · 본인 사진은 생성 이미지보다 우선 사용</small>
            </span>
            <label
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                upload(e.dataTransfer.files);
              }}
              className={`flex cursor-pointer items-center gap-4 rounded-[10px] border border-dashed p-[18px] text-[13px] text-muted transition-colors ${dragging ? "border-accent bg-accent-tint" : "border-line-strong bg-sunken hover:border-muted"}`}
            >
              <input
                type="file"
                accept=".jpg,.jpeg,.png,.webp,.mp4,.mov,.m4v,.webm"
                multiple
                className="sr-only"
                disabled={!project.input || project.busy}
                onChange={(e) => upload(e.target.files)}
              />
              <span className="grid size-10 flex-none place-items-center rounded-[10px] border border-line bg-card text-ink-2">
                <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M10 13V3.5M6 7.2l4-3.7 4 3.7M3.5 13.5v2a1.5 1.5 0 0 0 1.5 1.5h10a1.5 1.5 0 0 0 1.5-1.5v-2" />
                </svg>
              </span>
              <span className="min-w-0">
                <b className="font-semibold text-ink">
                  {project.input ? "사진·영상을 끌어다 놓거나 눌러서 고르세요" : "주제를 먼저 저장하면 사진을 올릴 수 있어요"}
                </b>
                <br />
                JPG · PNG · WEBP · MP4 · MOV · 장면 순서대로 쓰여요
                {saved.user_media.length > 0 && <span className="ml-1.5 text-ink-2">· {saved.user_media.length}장 올림</span>}
              </span>
              <span className="ml-auto hidden flex-none rounded-[10px] border border-line-strong px-4 py-2.5 font-semibold text-ink sm:inline">
                파일 선택
              </span>
            </label>
            {config && config.image_sources.length === 0 && saved.user_media.length === 0 && (
              <p className="text-[12px] text-stale-strong">
                이미지 방식이 &quot;본인 사진만&quot;이에요. 사진을 올리지 않으면 5단계에서 장면 이미지가 비어 6단계로 넘어갈
                수 없어요. <Link href="/settings">설정에서 무료 사진·AI 생성으로 바꾸기</Link>
                {config.image_unused?.length ? ` (${config.image_unused.join("·")} 키가 이미 있어요)` : ""}
              </p>
            )}
            {saved.user_media.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-2">
                {saved.user_media.map((m, i) => {
                  const url = fileUrl(project.id, m);
                  return url ? (
                    <span key={m} className="relative">
                      <SceneMedia src={url} path={m} className="h-20 w-[45px] rounded-[5px] border border-line-strong object-cover" />
                      <span className="absolute top-0.5 left-0.5 rounded bg-black/60 px-1 font-mono text-[9.5px] text-white">
                        S{i + 1}
                      </span>
                    </span>
                  ) : (
                    <span key={m} className="rounded border border-line bg-card px-2 py-1 font-mono text-[11px]" title={m}>
                      {m.split(/[\\/]/).pop()}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      <section className="mt-4 overflow-hidden rounded-[14px] border border-line bg-surface">
        <div className="flex items-center justify-between gap-3 border-b border-line px-[18px] py-3.5">
          <h3 className="text-[13.5px] font-semibold">검색 키워드</h3>
          <span className="text-[12px] text-muted">입력에서 뽑아요 · 해외 영상도 찾을 때는 앞의 2개, 아니면 3개로 검색해요</span>
        </div>
        <div className="flex flex-wrap items-center gap-2 p-[18px]">
          {draft.keywords.map((k) => (
            <span
              key={k}
              className="inline-flex h-8 items-center gap-2 rounded-full border border-line-strong bg-card pr-1.5 pl-3 text-[13px]"
            >
              {k}
              <button
                type="button"
                aria-label={`${k} 삭제`}
                className="grid size-5 place-items-center rounded-full text-muted hover:bg-line hover:text-ink"
                onClick={() => set("keywords", draft.keywords.filter((x) => x !== k))}
              >
                <svg viewBox="0 0 12 12" width="10" height="10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
                  <path d="M3 3l6 6M9 3l-6 6" />
                </svg>
              </button>
            </span>
          ))}
          {draft.keywords.length < 5 && (
            <input
              className="h-8 w-44 rounded-full border border-dashed border-line-strong bg-transparent px-3 text-[13px] text-ink outline-none placeholder:text-muted focus:border-accent"
              placeholder="+ 키워드 추가 (Enter)"
              value={kw}
              onChange={(e) => setKw(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addKeyword())}
            />
          )}
          {draft.keywords.length === 0 && (
            <span className="text-[13px] text-muted">비워 두면 1단계를 실행할 때 자동으로 만들어요</span>
          )}
        </div>
      </section>

      <div className="mt-4 flex flex-wrap items-center gap-2.5">
        <Button
          variant="ghost"
          disabled={!dirty || !draft.topic.trim() || project.busy}
          onClick={() => save("input", draft)}
        >
          {dirty ? "입력 저장" : "저장됨"}
        </Button>
        {dirty && <span className="text-[12.5px] text-stale">저장하면 뒤 단계에 ‘재생성 필요’가 붙어요</span>}
        <span className="ml-auto text-[12px] text-faint">한국·해외 검색 4번 = 약 410 units</span>
      </div>

      <StepActions
        project={project}
        step="s1"
        controls={controls}
        progress={progress}
        primaryLabel={draft.keywords.length ? "입력 정리 (S1 실행)" : "키워드 생성 (S1 실행)"}
        next="s2"
        beforeRun={dirty && draft.topic.trim() ? () => save("input", draft) : undefined}
      />
    </section>
  );
}
