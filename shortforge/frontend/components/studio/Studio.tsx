"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fileUrl } from "@/lib/api";
import { FACTOR_LABEL, MOOD_LABEL, VISUAL_STYLE_LABEL } from "@/lib/labels";
import { STEP_IDS, type AppConfig, type Input, type Project, type StepId } from "@/lib/types";
import { useNarrow } from "@/lib/useNarrow";
import { useProject, type StepProgress } from "@/lib/useProject";
import { VideoPlayer } from "../Media";
import { PublishChecklist } from "../PublishChecklist";
import { SetupNotice } from "../SetupNotice";
import { TimelinePreview } from "../TimelinePreview";
import { YouTubeModal } from "../YouTubeModal";
import { Brand, Button, Notice, ProgressBar, Seg } from "../ui";

// 쉬운 화면: 내부 7단계를 3단계로 묶어 보여 준다. 고를 필요 없는 단계는 자동으로 이어 간다.
// ① 아이디어(1~4단계 자동) ② 다듬기(5~6단계, 바꾸면 바로 미리보기) ③ 완성(7단계)
type View = "idea" | "edit" | "finish";
const VIEWS: { id: View; n: number; label: string }[] = [
  { id: "idea", n: 1, label: "아이디어" },
  { id: "edit", n: 2, label: "다듬기" },
  { id: "finish", n: 3, label: "완성" },
];

// 처음 쓰는 사람이 알아듣는 말로 (내부 단계 이름을 보이지 않는다)
const WORK: Record<StepId, string> = {
  s1: "주제를 정리하는 중",
  s2: "요즘 잘 된 비슷한 영상을 찾는 중",
  s3: "왜 잘 됐는지 살펴보는 중",
  s4: "대사와 장면을 쓰는 중",
  s5: "그림과 목소리를 만드는 중",
  s6: "장면 순서와 음악을 맞추는 중",
  s7: "영상을 만드는 중",
};
// 실패 안내에 쓰는 이름 ("…에서 문제가 생겼어요")
const STEP_NAME: Record<StepId, string> = {
  s1: "주제 정리",
  s2: "비슷한 영상 찾기",
  s3: "잘 된 이유 살펴보기",
  s4: "대사 쓰기",
  s5: "그림·목소리 만들기",
  s6: "장면 순서·음악 맞추기",
  s7: "영상 만들기",
};
const ROLE_EASY: Record<string, string> = {
  hook: "시작",
  problem: "고민",
  method: "방법",
  payoff: "결과",
  cta: "마무리",
};
const LOOK_OPTIONS = ["photo", "cinematic", "illustration", "watercolor"] as const;
// 완성 점검 결과를 쉬운 말과 할 일로 (LUFS 같은 말을 보이지 않는다)
const CHECK_EASY: Record<string, string> = {
  duration: "영상이 목표보다 길거나 짧아요. 다듬기에서 대사를 줄이거나 늘려 보세요.",
  loudness: "소리 크기가 조금 달라요. 다시 만들면 대부분 맞춰져요.",
  silence: "중간에 소리가 끊기는 곳이 있어요. 다듬기에서 그 장면 대사를 다시 저장해 보세요.",
  caption_width: "화면보다 긴 자막이 있어요. 다듬기에서 대사를 조금 짧게 해 주세요.",
};

export function Studio({ id }: { id: string }) {
  const { project, progress, error } = useProject(id);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [view, setView] = useState<View | null>(null); // 사용자가 고른 화면 (없으면 진행에 맞춰)
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const hash = window.location.hash;
    if (/^#s[1-7]$/.test(hash)) window.location.replace(`/p/${id}/pro${hash}`);
  }, [id]);

  useEffect(() => {
    api
      .config()
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  if (!project) {
    return error ? (
      <div className="p-10">
        <Notice tone="error">{error}</Notice>
      </div>
    ) : (
      <div className="p-10 text-muted">불러오는 중…</div>
    );
  }

  const st = project.status;
  const editable = st.s6 === "done" || !!project.timeline;
  const auto: View = st.s7 === "running" || st.s7 === "done" ? "finish" : editable ? "edit" : "idea";
  const current = view ?? auto;
  const failed = STEP_IDS.find((s) => st[s] === "error");
  const stuck = STEP_IDS.map((s) => project.not_ready?.[s]).find(Boolean) ?? null;
  const act = async (fn: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await fn();
    } catch (e) {
      setActionError((e as Error).message);
    }
  };
  const retry = () =>
    act(() => (failed === "s7" ? api.runStep(id, "s7") : api.runAll(id, failed ?? "s1", "s6")));
  const finish = () => {
    setView("finish");
    act(() => api.runStep(id, "s7"));
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-line bg-canvas/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6">
          <Brand />
          <nav aria-label="단계" className="order-3 flex w-full items-center gap-2 sm:order-none sm:w-auto">
            {VIEWS.map((v, i) => {
              const enabled = v.id === "idea" || (v.id === "edit" ? editable : editable || !!project.render);
              return (
                <span key={v.id} className="flex items-center gap-2">
                  {i > 0 && <span className="h-px w-5 bg-line-strong sm:w-8" aria-hidden="true" />}
                  <button
                    type="button"
                    disabled={!enabled}
                    aria-current={current === v.id ? "step" : undefined}
                    onClick={() => setView(v.id)}
                    className="flex items-center gap-2 rounded-full px-3 py-1.5 text-[14px] text-muted enabled:hover:text-ink disabled:opacity-40 aria-[current=step]:bg-accent-tint aria-[current=step]:font-semibold aria-[current=step]:text-accent"
                  >
                    <span className="grid size-6 place-items-center rounded-full border border-current text-[12px]">
                      {v.n}
                    </span>
                    {v.label}
                  </button>
                </span>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-4 text-[13px]">
            <Link href="/settings" className="text-muted hover:text-ink">
              설정
            </Link>
            <Link href={`/p/${id}/pro`} className="text-muted hover:text-ink" title="7단계를 하나씩 자세히 다루는 화면">
              전문가 화면
            </Link>
          </div>
        </div>
      </header>
      <SetupNotice config={config} />

      <main className="mx-auto max-w-[1280px] px-4 pt-8 pb-20 sm:px-6">
        <h1 className="text-[26px] leading-tight font-bold tracking-[-0.025em] sm:text-[30px]">
          {project.input?.topic ?? "새 영상"}
        </h1>

        {failed && !project.busy && (
          <div className="mt-5">
            <Notice tone="error">
              <div className="flex flex-wrap items-center gap-3">
                <span className="min-w-[220px] flex-1">
                  {project.errors[failed]?.startsWith("중간에 멈췄어요")
                    ? `${STEP_NAME[failed]} 중에 프로그램이 꺼져 멈췄어요. 다시 시도를 누르면 이어서 만들어요.`
                    : `${STEP_NAME[failed]}에서 문제가 생겼어요. 다시 시도해 보고, 계속 안 되면 설정에서 키를 확인해 주세요.`}
                  <details className="mt-1 text-[12.5px] opacity-80">
                    <summary className="cursor-pointer">자세히</summary>
                    {project.errors[failed]}
                  </details>
                </span>
                <Button onClick={retry}>다시 시도</Button>
              </div>
            </Notice>
          </div>
        )}
        {stuck && !project.busy && !failed && (
          <div className="mt-5">
            <Notice tone="warn">
              <div className="flex flex-wrap items-center gap-3">
                <span className="min-w-[220px] flex-1">
                  장면 그림이 없어 다음으로 넘어갈 수 없어요. 설정에서 그림을 만드는 방법(AI 그림·무료 사진)을
                  고르거나, 전문가 화면에서 내 사진을 올려 주세요.
                  <details className="mt-1 text-[12.5px] opacity-80">
                    <summary className="cursor-pointer">자세히</summary>
                    {stuck}
                  </details>
                </span>
                <Link href="/settings" className="font-semibold">
                  설정 열기
                </Link>
                <Link href={`/p/${id}/pro#s5`}>전문가 화면</Link>
              </div>
            </Notice>
          </div>
        )}
        {actionError && (
          <div className="mt-5">
            <Notice tone="error">{actionError}</Notice>
          </div>
        )}

        {current === "idea" && <IdeaView project={project} progress={progress} onStart={(from) => act(() => api.runAll(id, from, "s6"))} />}
        {current === "edit" && <EditView project={project} progress={progress} act={act} onFinish={finish} />}
        {current === "finish" && <FinishView project={project} progress={progress} act={act} />}
      </main>
    </div>
  );
}

/** 지금 무엇을 하고 있는지 쉬운 말로 */
function Working({ project, progress }: { project: Project; progress: Partial<Record<StepId, StepProgress>> }) {
  const running = STEP_IDS.find((s) => project.status[s] === "running");
  if (!running) return null;
  const p = progress[running]?.progress ?? 0;
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-line bg-surface px-5 py-4">
      <div className="flex items-center gap-2.5 text-[15px] font-medium">
        <span className="sf-pulse size-2 rounded-full bg-accent" />
        {WORK[running]}…
      </div>
      <ProgressBar value={p} />
    </div>
  );
}

// ── ① 아이디어 ─────────────────────────────────────────────

function IdeaView({
  project,
  progress,
  onStart,
}: {
  project: Project;
  progress: Partial<Record<StepId, StepProgress>>;
  onStart: (from: StepId) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const refs = (project.refs ?? []).filter((r) => r.selected);
  const factors = (project.factors ?? []).slice(0, 4);
  // 아직 시작하지 않았거나 중간에 멈춘 프로젝트(예: 복제본): 남은 단계를 다듬기 직전까지 이어서
  const next = STEP_IDS.find((s) => project.status[s] !== "done");
  const failed = STEP_IDS.some((s) => project.status[s] === "error");
  const stuck = STEP_IDS.some((s) => project.not_ready?.[s]);
  const canGo =
    !project.busy && !failed && !stuck && !!next && STEP_IDS.indexOf(next) <= STEP_IDS.indexOf("s6");
  const fresh = STEP_IDS.every((s) => project.status[s] === "idle");
  const shown = refs.find((r) => r.video_id === open);

  return (
    <div className="mt-6 flex flex-col gap-8">
      <p className="text-[15px] text-ink-2">
        요즘 잘 된 비슷한 영상을 찾아 왜 잘 됐는지 살펴보고, 그 방식으로 대사와 장면을 써요. 끝나면 자동으로 다음
        단계로 넘어가요.
      </p>
      {canGo && (
        <div>
          <Button className="min-h-12 px-6 text-[15px]" onClick={() => onStart(next!)}>
            {fresh ? "만들기 시작" : "이어서 만들기"}
          </Button>
        </div>
      )}
      <Working project={project} progress={progress} />

      {refs.length > 0 && (
        <section>
          <h2 className="text-[19px] font-bold">참고한 영상</h2>
          <p className="mt-1 text-[13.5px] text-muted">눌러서 크게 볼 수 있어요.</p>
          <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            {refs.map((r) => (
              <button key={r.video_id} type="button" onClick={() => setOpen(r.video_id)} className="group flex flex-col gap-2 text-left">
                <span className="relative block aspect-[9/16] overflow-hidden rounded-2xl border border-line-strong bg-sunken">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={r.thumbnail_url} alt="" loading="lazy" className="h-full w-full scale-[1.34] object-cover" />
                  <span className="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100">
                    <span className="rounded-full bg-black/60 px-3 py-1.5 text-[13px] text-white">크게 보기</span>
                  </span>
                </span>
                <span className="line-clamp-2 text-[13.5px] leading-snug text-ink">{r.title}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {factors.length > 0 && (
        <section>
          <h2 className="text-[19px] font-bold">잘 된 이유</h2>
          <ul className="mt-3 grid gap-3 md:grid-cols-2">
            {factors.map((f) => (
              <li key={f.name} className="rounded-2xl border border-line bg-surface px-5 py-4">
                <div className="text-[13px] font-semibold text-accent">{FACTOR_LABEL[f.name].replace(/ \(.*\)/, "")}</div>
                <p className="mt-1 text-[14px] leading-relaxed text-ink-2">{f.finding}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {shown && <YouTubeModal videoId={shown.video_id} title={shown.title} onClose={() => setOpen(null)} />}
    </div>
  );
}

// ── ② 다듬기 ─────────────────────────────────────────────

function EditView({
  project,
  progress,
  act,
  onFinish,
}: {
  project: Project;
  progress: Partial<Record<StepId, StepProgress>>;
  act: (fn: () => Promise<unknown>) => Promise<void>;
  onFinish: () => void;
}) {
  const narrow = useNarrow();
  const [focus, setFocus] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const scenes = project.strategy?.scenes ?? [];
  const input = project.input as Input;
  const tl = project.timeline;
  const busy = project.busy || saving !== null;
  const changed = project.status.s5 !== "done" || project.status.s6 !== "done";
  const target = input.duration_sec;
  const length = (tl?.scenes ?? []).reduce((t, s) => t + (typeof s.duration === "number" ? s.duration : 0), 0);

  // 그림체·목소리는 그림·음성을 새로 만들어야 해서, 고르면 바로 다시 만든다(따로 누를 버튼 없이)
  const remake = (patch: Partial<Input>) =>
    Object.entries(patch).every(([k, v]) => input[k as keyof Input] === v) ||
    act(async () => {
      await api.patch(project.id, "input", { ...input, ...patch });
      await api.runAll(project.id, "s5", "s6");
    });
  const saveLine = (sceneId: string, text: string) =>
    act(async () => {
      setSaving(sceneId);
      try {
        await api.setLine(project.id, sceneId, text); // 그 장면 음성만 다시 만들어 미리보기에 반영
      } finally {
        setSaving(null);
      }
    });

  return (
    <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_auto]">
      <div className="flex min-w-0 flex-col gap-6 lg:order-1">
        <p className="text-[15px] text-ink-2">
          대사를 고치거나 분위기를 고르면 미리보기에 바로 반영돼요. 마음에 들면 아래에서 영상을 완성하세요.
        </p>
        <Working project={project} progress={progress} />
        {changed && !project.busy && (
          <Notice tone="warn">
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex-1">바뀐 내용을 아직 반영하지 않았어요.</span>
              <Button onClick={() => act(() => api.runAll(project.id, project.status.s5 !== "done" ? "s5" : "s6", "s6"))}>
                반영하기
              </Button>
            </div>
          </Notice>
        )}

        <section className="flex flex-col gap-3">
          <h2 className="flex items-baseline gap-3 text-[19px] font-bold">
            대사
            {length > 0 && (
              <span
                className={`text-[13px] font-normal tabular-nums ${Math.abs(length - target) > target * 0.15 ? "text-stale" : "text-muted"}`}
              >
                지금 약 {Math.round(length)}초 · 목표 {target}초
                {length > target * 1.15 ? " — 조금 줄여 주세요" : length < target * 0.85 ? " — 조금 늘려도 좋아요" : ""}
              </span>
            )}
          </h2>
          {scenes.map((s, i) => (
            <LineEditor
              key={`${s.id}-${s.line}`}
              index={i + 1}
              role={ROLE_EASY[s.role] ?? ""}
              line={s.line}
              saving={saving === s.id}
              disabled={busy}
              onFocus={() => setFocus(s.id)}
              onSave={(text) => saveLine(s.id, text)}
            />
          ))}
        </section>

        <section className="grid gap-5 sm:grid-cols-2">
          <Choice label="그림 느낌">
            <Seg
              label="그림 느낌"
              disabled={busy}
              value={input.visual_style}
              onChange={(v) => remake({ visual_style: v })}
              options={(["auto", ...LOOK_OPTIONS] as const).map((v) => ({ value: v, label: VISUAL_STYLE_LABEL[v] }))}
            />
          </Choice>
          <Choice label="목소리">
            <Seg
              label="목소리"
              disabled={busy}
              value={input.voice}
              onChange={(v) => remake({ voice: v })}
              options={[
                { value: "auto", label: "자동" },
                { value: "female", label: "여성" },
                { value: "male", label: "남성" },
              ]}
            />
          </Choice>
          {tl && (
            <Choice label="배경음악" wide>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="배경음악">
                {Object.entries(MOOD_LABEL).map(([mood, label]) => (
                  <button
                    key={mood}
                    type="button"
                    disabled={busy}
                    aria-pressed={!!tl.audio.bgm && tl.audio.mood === mood}
                    onClick={() => act(() => api.setMusic(project.id, { mood }))}
                    className="rounded-full border border-line-strong px-3.5 py-1.5 text-[13px] text-ink-2 enabled:hover:text-ink disabled:opacity-50 aria-pressed:border-accent aria-pressed:bg-accent-tint aria-pressed:text-accent"
                  >
                    {label}
                  </button>
                ))}
                <button
                  type="button"
                  disabled={busy}
                  aria-pressed={!tl.audio.bgm}
                  onClick={() => act(() => api.setMusic(project.id, { off: true }))}
                  className="rounded-full border border-line-strong px-3.5 py-1.5 text-[13px] text-ink-2 enabled:hover:text-ink disabled:opacity-50 aria-pressed:border-accent aria-pressed:bg-accent-tint aria-pressed:text-accent"
                >
                  음악 없음
                </button>
              </div>
            </Choice>
          )}
        </section>

        <div className="flex flex-wrap items-center gap-3 border-t border-line pt-6">
          <Button className="min-h-12 px-6 text-[15px]" disabled={busy || changed} onClick={onFinish}>
            영상 완성하기 →
          </Button>
          <span className="text-[13px] text-muted">1~3분쯤 걸려요.</span>
        </div>
      </div>

      <aside className="order-first flex flex-col items-center gap-3 lg:sticky lg:top-24 lg:order-2 lg:self-start">
        {tl ? (
          <div className="relative">
            <TimelinePreview
              projectId={project.id}
              timeline={tl}
              version={project.version}
              width={narrow ? 300 : 380}
              compact
              focus={focus}
            />
            {busy && (
              <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-black/50 text-[14px] text-white">
                {saving ? "목소리를 새로 만드는 중…" : "새로 만드는 중…"}
              </div>
            )}
          </div>
        ) : (
          <div className="sf-skel aspect-[9/16] w-[300px] rounded-xl" aria-hidden="true" />
        )}
        <p className="max-w-[380px] text-center text-[12.5px] text-muted">
          미리보기예요. 완성 영상에서는 자막이 말에 맞춰 나오고 목소리가 나올 때 음악이 작아져요.
        </p>
      </aside>
    </div>
  );
}

function Choice({ label, wide = false, children }: { label: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <div className={`flex min-w-0 flex-col gap-2 ${wide ? "sm:col-span-2" : ""}`}>
      <span className="text-[14px] font-semibold">{label}</span>
      {children}
    </div>
  );
}

/** 장면 대사 한 줄: 다 고치고 칸을 벗어나면 그 장면 목소리만 새로 만든다 */
function LineEditor({
  index,
  role,
  line,
  saving,
  disabled,
  onFocus,
  onSave,
}: {
  index: number;
  role: string;
  line: string;
  saving: boolean;
  disabled: boolean;
  onFocus: () => void;
  onSave: (text: string) => void;
}) {
  const [draft, setDraft] = useState(line);
  return (
    <label className="flex flex-col gap-1.5 rounded-2xl border border-line bg-surface px-4 py-3 focus-within:border-accent">
      <span className="flex items-center gap-2 text-[12.5px] text-muted">
        <b className="text-ink-2">장면 {index}</b> {role}
        {saving && <span className="ml-auto text-accent">목소리 새로 만드는 중…</span>}
      </span>
      <textarea
        rows={2}
        value={draft}
        disabled={disabled}
        maxLength={200}
        onFocus={onFocus}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          if (!draft.trim()) setDraft(line); // 비우면 원래 대사로
          else if (draft.trim() !== line.trim()) onSave(draft.trim());
        }}
        className="resize-none bg-transparent text-[16px] leading-relaxed text-ink outline-none disabled:opacity-60"
      />
    </label>
  );
}

// ── ③ 완성 ───────────────────────────────────────────────

function FinishView({
  project,
  progress,
  act,
}: {
  project: Project;
  progress: Partial<Record<StepId, StepProgress>>;
  act: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const narrow = useNarrow();
  const r = project.render;
  const done = project.status.s7 === "done" && r;
  const running = project.status.s7 === "running";
  const video = (done || project.status.s7 === "stale") && r ? fileUrl(project.id, r.path, project.version) : null;
  const failed = done ? r.checks.filter((c) => !c.ok) : [];
  const stale = project.status.s7 === "stale" && !!r;
  const shown = (done || stale) && r;
  const make = () => act(() => api.runStep(project.id, "s7"));

  return (
    <div className="mt-6 grid gap-8 lg:grid-cols-[auto_minmax(0,1fr)]">
      <div className="flex flex-col items-center gap-3">
        {video ? (
          <VideoPlayer
            key={video}
            src={video}
            className="aspect-[9/16] rounded-2xl border border-line-strong"
            style={{ width: narrow ? 320 : 420 }}
          />
        ) : (
          <div
            className="flex aspect-[9/16] flex-col items-center justify-center gap-3 rounded-2xl border border-line-strong bg-surface p-8 text-center text-[15px] text-muted"
            style={{ width: narrow ? 320 : 420 }}
          >
            {running ? (
              <>
                <span className="sf-pulse size-2.5 rounded-full bg-accent" />
                영상을 만드는 중… {Math.round((progress.s7?.progress ?? 0) * 100)}%
              </>
            ) : (
              <>
                아직 영상을 만들지 않았어요
                <Button onClick={make} disabled={project.busy}>
                  영상 만들기
                </Button>
              </>
            )}
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-col gap-5">
        {stale && !running && (
          <Notice tone="warn">
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex-1">바꾼 내용이 아직 영상에 들어가지 않았어요. 다시 만들면 반영돼요.</span>
              <Button onClick={make} disabled={project.busy}>
                다시 만들기
              </Button>
            </div>
          </Notice>
        )}
        {shown ? (
          <>
            <div className="rounded-2xl border border-line bg-surface px-5 py-4">
              <div className="text-[17px] font-bold">
                {failed.length === 0
                  ? "영상이 완성됐어요 🎉"
                  : failed.length === 1
                    ? "거의 다 됐어요. 한 가지만 확인해 주세요"
                    : `거의 다 됐어요. ${failed.length}가지를 확인해 주세요`}
              </div>
              {failed.length > 0 ? (
                <ul className="mt-2 list-disc pl-5 text-[14px] text-ink-2">
                  {failed.map((c) => (
                    <li key={c.id}>{CHECK_EASY[c.id] ?? c.detail}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-[14px] text-muted">길이·소리 크기·자막을 자동으로 확인했고 모두 괜찮아요.</p>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <a
                  href={fileUrl(project.id, r.path, project.version, true) ?? undefined}
                  className="inline-flex min-h-12 items-center rounded-[10px] bg-accent px-6 text-[15px] font-semibold text-accent-ink no-underline hover:bg-accent-strong hover:text-accent-ink"
                >
                  영상 내려받기
                </a>
                <a
                  href={fileUrl(project.id, r.srt, project.version, true) ?? undefined}
                  className="inline-flex min-h-12 items-center rounded-[10px] border border-line-strong px-5 text-[14px] text-ink no-underline hover:bg-card hover:text-ink"
                >
                  자막 파일
                </a>
                {project.render_outdated && (
                  <Button variant="ghost" className="min-h-12" disabled={project.busy} onClick={make}>
                    새 방식으로 다시 만들기
                  </Button>
                )}
              </div>
            </div>
            <PublishChecklist projectId={project.id} version={project.version} />
          </>
        ) : (
          <p className="text-[15px] text-ink-2">
            그림·목소리·자막·음악을 하나의 세로 영상으로 합쳐요. 끝나면 여기서 바로 보고 내려받을 수 있어요.
          </p>
        )}
      </div>
    </div>
  );
}
