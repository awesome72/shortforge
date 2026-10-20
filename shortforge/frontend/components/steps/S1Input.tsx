"use client";

import Link from "next/link";
import { useState } from "react";
import { api, fileUrl } from "@/lib/api";
import { TONE_LABEL } from "@/lib/labels";
import type { Input } from "@/lib/types";
import { StepActions, StepHeader } from "../StepActions";
import type { StepProps } from "../Workspace";
import { Button, Field, inputClass } from "../ui";

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
        desc="입력은 다음 단계의 검색 키워드와 전략의 제약 조건으로 그대로 쓰입니다."
      />
      <div className="grid grid-cols-2 gap-4">
        <Field label="주제 / 하고 싶은 이야기" wide>
          <input
            className={inputClass}
            value={draft.topic}
            placeholder="예: 퇴근 후 10분 홈트로 3개월간 바뀐 점"
            onChange={(e) => set("topic", e.target.value)}
          />
        </Field>
        <Field label="타깃 시청자">
          <input className={inputClass} value={draft.audience} onChange={(e) => set("audience", e.target.value)} />
        </Field>
        <Field label="톤">
          <select
            className={inputClass}
            value={draft.tone}
            onChange={(e) => set("tone", e.target.value as Input["tone"])}
          >
            {Object.entries(TONE_LABEL).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field label="길이">
          <select
            className={inputClass}
            value={draft.duration_sec}
            onChange={(e) => set("duration_sec", Number(e.target.value) as Input["duration_sec"])}
          >
            {[30, 15, 60].map((d) => (
              <option key={d} value={d}>
                {d}초
              </option>
            ))}
          </select>
        </Field>
        <Field label="언어 · 지역">
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
        </Field>

        <div className="col-span-2 flex flex-col gap-1.5">
          <span className="text-[13px] font-medium text-ink-2">
            내 소재 (선택) — 본인 사진은 생성 이미지보다 우선 사용
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
            className={`flex min-h-[72px] cursor-pointer items-center justify-center rounded-lg border border-dashed px-4 text-muted ${dragging ? "border-accent bg-accent-tint" : "border-line-dash bg-surface"}`}
          >
            <input
              type="file"
              accept=".jpg,.jpeg,.png,.webp"
              multiple
              className="sr-only"
              disabled={!project.input || project.busy}
              onChange={(e) => upload(e.target.files)}
            />
            {project.input ? "사진 끌어다 놓기 또는 클릭 (jpg · png · webp)" : "주제를 먼저 저장하면 사진을 올릴 수 있다"}
          </label>
          {config && config.image_sources.length === 0 && saved.user_media.length === 0 && (
            <p className="text-[12px] text-stale-strong">
              이미지 방식이 &quot;본인 사진만&quot;이다. 사진을 올리지 않으면 5단계에서 장면 이미지가 비어 6단계로 갈 수
              없다.{" "}
              <Link href="/settings">설정에서 무료 사진·AI 생성으로 바꾸기</Link>
              {config.image_unused?.length ? ` (${config.image_unused.join("·")} 키가 이미 있다)` : ""}
            </p>
          )}
          {saved.user_media.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-2">
              {saved.user_media.map((m) => {
                const url = fileUrl(project.id, m);
                return url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key={m} src={url} alt="" className="h-20 w-[45px] rounded border border-line object-cover" />
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

      <div className="mt-6">
        <div className="mb-2 text-[13px] font-medium text-ink-2">LLM이 만든 검색 키워드 (편집 가능, 3~5개)</div>
        <div className="flex flex-wrap items-center gap-2">
          {draft.keywords.map((k) => (
            <span
              key={k}
              className="inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-card px-3 py-1 text-[13px]"
            >
              {k}
              <button
                type="button"
                aria-label={`${k} 삭제`}
                className="text-muted hover:text-err"
                onClick={() => set("keywords", draft.keywords.filter((x) => x !== k))}
              >
                ×
              </button>
            </span>
          ))}
          {draft.keywords.length < 5 && (
            <input
              className={`${inputClass} min-h-8 w-44 py-1`}
              placeholder="키워드 추가 + Enter"
              value={kw}
              onChange={(e) => setKw(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addKeyword())}
            />
          )}
          {draft.keywords.length === 0 && (
            <span className="text-[13px] text-muted">비워 두면 S1 실행 시 LLM이 만든다</span>
          )}
        </div>
      </div>

      <div className="mt-6 flex flex-wrap gap-2.5">
        <Button
          variant="ghost"
          disabled={!dirty || !draft.topic.trim() || project.busy}
          onClick={() => save("input", draft)}
        >
          {dirty ? "입력 저장" : "저장됨"}
        </Button>
        {dirty && <span className="self-center text-[13px] text-stale">저장하면 뒤 단계에 &quot;재생성 필요&quot;가 붙는다</span>}
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
