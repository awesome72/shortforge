"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, fileUrl } from "@/lib/api";
import { FACTOR_LABEL, MOOD_LABEL, VISUAL_STYLE_LABEL } from "@/lib/labels";
import { STEP_IDS, type AppConfig, type Input, type Project, type StepId } from "@/lib/types";
import { useNarrow } from "@/lib/useNarrow";
import { useProject, type StepProgress } from "@/lib/useProject";
import { SceneMedia, VideoPlayer } from "../Media";
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
// 남은 시간 어림에 쓰는 단계별 시간(초). 실제 키로 잰 값이고 s5는 실측 중앙값이다.
// 예상보다 많이 걸리면 '평소보다 오래 걸려요'로 바꿔 말한다
const STEP_SEC: Record<StepId, number> = { s1: 2, s2: 3, s3: 23, s4: 33, s5: 39, s6: 5, s7: 60 };
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
  silence: "중간에 소리가 끊기는 곳이 있어요. 영상을 들어 보고, 어색하면 다듬기에서 그 대사를 조금 바꿔 보세요.",
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
  // 그림·목소리를 만들었으면 다듬을 수 있다(그림이 빈 장면은 다듬기에서 내 사진을 올린다)
  const editable = st.s6 === "done" || !!project.timeline || (st.s5 === "done" && !!project.assets);
  const auto: View = st.s7 === "running" || st.s7 === "done" ? "finish" : editable ? "edit" : "idea";
  const current = view ?? auto;
  const failed = STEP_IDS.find((s) => st[s] === "error");
  const stuck = STEP_IDS.map((s) => project.not_ready?.[s]).find(Boolean) ?? null;
  const canGenerate = !!config?.can_generate; // 지금 AI 그림·무료 사진을 얻을 수 있다
  const noImage = (project.assets ?? []).some((a) => !a.image.path);
  const act = async (fn: () => Promise<unknown>, keepError = false) => {
    if (!keepError) setActionError(null);
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
                  {!noImage
                    ? "목소리가 없는 장면이 있어요. 버튼을 누르면 다시 만들어요."
                    : canGenerate
                      ? "그림이 없는 장면이 있어요. 버튼을 누르면 빈 장면의 그림을 한 번에 만들어요. 그래도 안 되면 잠시 뒤 다시 하거나 장면마다 '내 사진'을 올려 주세요."
                      : "그림이 없는 장면이 있어요. 다듬기에서 장면마다 '내 사진'을 올리거나, 설정에서 그림을 만드는 방법(AI 그림·무료 사진)을 골라 주세요."}
                </span>
                {canGenerate || !noImage ? (
                  <Button onClick={() => act(() => api.runAll(id, "s5", "s6"))}>
                    {noImage ? "빈 장면 그림 만들기" : "다시 만들기"}
                  </Button>
                ) : (
                  <Link href="/settings" className="font-semibold">
                    설정 열기
                  </Link>
                )}
                {current !== "edit" && (
                  <button type="button" className="font-semibold text-accent" onClick={() => setView("edit")}>
                    장면에 사진 올리기
                  </button>
                )}
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
        {current === "edit" && (
          <EditView project={project} progress={progress} act={act} onFinish={finish} config={config} />
        )}
        {current === "finish" && (
          <FinishView project={project} progress={progress} act={act} onEdit={() => setView("edit")} />
        )}
      </main>
    </div>
  );
}

/** 지금 무엇을 하고 있는지 쉬운 말로 */
function Working({
  project,
  progress,
  overall = false,
}: {
  project: Project;
  progress: Partial<Record<StepId, StepProgress>>;
  overall?: boolean; // 다듬기 전까지(1~6단계) 전체 진행과 남은 시간을 보여 준다
}) {
  const running = STEP_IDS.find((s) => project.status[s] === "running");
  const waiting = !!running && running !== "s7" && overall;
  // 실행이 시작된 뒤 지난 초 (예상보다 오래 걸리는지 보려고). 진행 소식이 없어도 문구를 고친다
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!waiting) return;
    const start = Date.now();
    const t = window.setInterval(() => setElapsed((Date.now() - start) / 1000), 5000);
    return () => {
      window.clearInterval(t);
      setElapsed(0);
    };
  }, [waiting]);
  const expected = useRef(0); // 시작할 때 예상한 남은 초
  if (!running) return null;
  const p = progress[running]?.progress ?? 0;
  let value = p;
  let left: string | null = null;
  if (overall && running !== "s7") {
    const steps = STEP_IDS.filter((s) => s !== "s7");
    const all = steps.reduce((t, s) => t + STEP_SEC[s], 0);
    const rest = steps.reduce(
      (t, s) => t + (project.status[s] === "done" ? 0 : STEP_SEC[s] * (s === running ? 1 - p : 1)),
      0,
    );
    // eslint-disable-next-line react-hooks/refs -- 틱이 돌기 전(0초)의 값이 시작 때의 예상이다
    if (elapsed === 0) expected.current = rest;
    // eslint-disable-next-line react-hooks/refs
    const slow = elapsed > Math.max(60, expected.current * 2);
    value = 1 - rest / all;
    left = slow
      ? "평소보다 오래 걸려요"
      : rest < 45
        ? "거의 다 됐어요"
        : `앞으로 ${Math.max(1, Math.round(rest / 60))}분쯤`;
  }
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-line bg-surface px-5 py-4">
      <div className="flex items-center gap-2.5 text-[15px] font-medium">
        <span className="sf-pulse size-2 rounded-full bg-accent" />
        {WORK[running]}…
        {left && <span className="ml-auto text-[13px] font-normal text-muted">{left}</span>}
      </div>
      <ProgressBar value={value} />
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
      <Working project={project} progress={progress} overall />

      {project.strategy && (
        <section>
          <h2 className="text-[19px] font-bold">이렇게 말할 거예요</h2>
          <p className="mt-1 text-[13.5px] text-muted">그림과 목소리를 만든 뒤 다듬기에서 고칠 수 있어요.</p>
          <ol className="mt-3 flex flex-col gap-2">
            {project.strategy.scenes.map((s, i) => (
              <li key={s.id} className="flex gap-3 rounded-2xl border border-line bg-surface px-4 py-3">
                <span className="w-14 flex-none text-[12.5px] text-muted">
                  <b className="text-ink-2">장면 {i + 1}</b>
                  <br />
                  {ROLE_EASY[s.role] ?? ""}
                </span>
                <span className="text-[15px] leading-relaxed text-ink">{s.line}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

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
  config,
}: {
  project: Project;
  progress: Partial<Record<StepId, StepProgress>>;
  act: (fn: () => Promise<unknown>, keepError?: boolean) => Promise<void>;
  onFinish: () => void;
  config: AppConfig | null;
}) {
  const narrow = useNarrow();
  const [focus, setFocus] = useState<string | null>(null);
  const [saving, setSaving] = useState<string[]>([]); // 저장 중이거나 저장을 기다리는 장면
  const [unsaved, setUnsaved] = useState<string[]>([]); // 저장하지 못한 장면
  const [picturing, setPicturing] = useState<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve()); // 서버는 한 번에 한 편집만 받는다
  const scenes = project.strategy?.scenes ?? [];
  const input = project.input as Input;
  const tl = project.timeline;
  const busy = project.busy || saving.length > 0 || picturing !== null;
  // 대사 칸은 저장 중인 장면만 잠근다. busy는 대사 저장 중에도 참이라 단계 실행으로만 판단한다
  const locked = STEP_IDS.some((s) => project.status[s] === "running") || picturing !== null;
  const canGenerate = !!config?.can_generate;
  const images = Object.fromEntries((project.assets ?? []).map((a) => [a.scene_id, a.image]));
  const missing = scenes.filter((s) => !images[s.id]?.path).length;
  const changed = project.status.s5 !== "done" || project.status.s6 !== "done";

  // 그림을 바꾸면 서버가 그 장면만 지시서에 반영한다. 6단계 전이면 빈 장면이 다 찼을 때 한 번 맞춘다
  const picture = (sceneId: string, change: () => Promise<unknown>) =>
    act(async () => {
      setPicturing(sceneId);
      setFocus(sceneId);
      try {
        await queue.current; // 대사 저장이 끝난 뒤 (서버는 한 번에 한 편집만 받는다)
        await change(); // 6단계가 끝나 있으면 서버가 그 장면만 지시서에 바로 반영한다
        const p = await api.get(project.id);
        // 아직 6단계 전이면(빈 장면을 채우는 중) 모두 채워졌을 때 한 번 맞춘다
        if (p.status.s6 !== "done" && (p.assets ?? []).every((a) => a.image.path))
          await api.runAll(project.id, "s6", "s6");
      } finally {
        setPicturing(null);
      }
    });
  const otherPicture = (sceneId: string) => picture(sceneId, () => api.regenerateImage(project.id, sceneId));
  const ownPhoto = (sceneId: string, file: File | undefined) =>
    file &&
    picture(sceneId, async () => {
      const { saved } = await api.upload(project.id, [file], false); // 1단계 사진 목록은 건드리지 않는다
      await api.setScenePhoto(project.id, sceneId, saved[0]);
    });
  const target = input.duration_sec;
  const length = (tl?.scenes ?? []).reduce((t, s) => t + (typeof s.duration === "number" ? s.duration : 0), 0);

  // 그림체·목소리는 그림·음성을 새로 만들어야 해서, 고르면 바로 다시 만든다(따로 누를 버튼 없이)
  const remake = (patch: Partial<Input>) =>
    Object.entries(patch).every(([k, v]) => input[k as keyof Input] === v) ||
    act(async () => {
      await api.patch(project.id, "input", { ...input, ...patch });
      await api.runAll(project.id, "s5", "s6");
    });
  const saveLine = (sceneId: string, text: string) => {
    setSaving((s) => [...s, sceneId]);
    const run = () =>
      act(async () => {
        try {
          await api.setLine(project.id, sceneId, text); // 그 장면 음성만 다시 만들어 미리보기에 반영
          setUnsaved((s) => s.filter((x) => x !== sceneId));
        } catch (e) {
          setUnsaved((s) => [...s, sceneId]);
          throw e;
        } finally {
          setSaving((s) => s.filter((x) => x !== sceneId));
        }
      }, true); // 앞 저장의 오류가 다음 저장 시작에 지워지지 않게
    queue.current = queue.current.then(run, run);
    return queue.current;
  };

  return (
    <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_auto]">
      <div className="flex min-w-0 flex-col gap-6 lg:order-1">
        <p className="text-[15px] text-ink-2">
          대사를 고치거나 분위기를 고르면 미리보기에 바로 반영돼요. 마음에 들면 아래에서 영상을 완성하세요.
        </p>
        <Working project={project} progress={progress} />
        {changed && !project.busy && missing === 0 && (
          <Notice tone="warn">
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex-1">바뀐 내용을 아직 반영하지 않았어요.</span>
              <Button
                disabled={busy}
                onClick={() => act(() => api.runAll(project.id, project.status.s5 !== "done" ? "s5" : "s6", "s6"))}
              >
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
              saving={saving.includes(s.id)}
              failed={unsaved.includes(s.id)}
              disabled={locked || saving.includes(s.id)}
              onFocus={() => setFocus(s.id)}
              onSave={(text) => saveLine(s.id, text)}
              media={
                <ScenePicture
                  src={fileUrl(project.id, images[s.id]?.path, project.version)}
                  path={images[s.id]?.path}
                  working={picturing === s.id}
                  disabled={locked} // 대사 저장 중에 잠그면 Tab으로 넘어온 커서가 사라진다
                  canGenerate={canGenerate}
                  onOther={() => otherPicture(s.id)}
                  onOwn={(file) => ownPhoto(s.id, file)}
                />
              }
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
                {saving.length ? "목소리를 새로 만드는 중…" : picturing ? "그림을 바꾸는 중…" : "새로 만드는 중…"}
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
  failed,
  disabled,
  onFocus,
  onSave,
  media,
}: {
  index: number;
  role: string;
  line: string;
  saving: boolean;
  failed: boolean;
  disabled: boolean;
  onFocus: () => void;
  onSave: (text: string) => void;
  media?: React.ReactNode;
}) {
  const [draft, setDraft] = useState(line);
  return (
    <div className="flex gap-3.5 rounded-2xl border border-line bg-surface px-3.5 py-3 focus-within:border-accent">
      {media}
      <label className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="flex items-center gap-2 text-[12.5px] text-muted">
          <b className="text-ink-2">장면 {index}</b> {role}
          {saving && <span className="ml-auto text-accent">목소리 새로 만드는 중…</span>}
          {failed && !saving && <span className="ml-auto text-err">저장하지 못했어요. 칸을 다시 눌렀다가 벗어나 주세요</span>}
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
    </div>
  );
}

/** 장면 그림 한 장: 작게 보여 주고, 그 장면만 다른 그림으로 바꾸거나 내 사진·영상으로 바꾼다 */
function ScenePicture({
  src,
  path,
  working,
  disabled,
  canGenerate,
  onOther,
  onOwn,
}: {
  src: string | null;
  path?: string | null;
  working: boolean;
  disabled: boolean;
  canGenerate: boolean;
  onOther: () => void;
  onOwn: (file: File | undefined) => void;
}) {
  return (
    <div className="flex w-[76px] flex-none flex-col items-stretch gap-1">
      <div className="relative aspect-[9/16] overflow-hidden rounded-lg border border-line-strong bg-sunken">
        {src ? (
          <SceneMedia src={src} path={path} className="h-full w-full object-cover" />
        ) : (
          <span className="flex h-full items-center justify-center px-1 text-center text-[11.5px] text-stale">
            그림 없음
          </span>
        )}
        {working && (
          <span className="absolute inset-0 flex items-center justify-center bg-black/55 text-[11px] text-white">
            바꾸는 중…
          </span>
        )}
      </div>
      {canGenerate && (
        <button
          type="button"
          disabled={disabled}
          onClick={onOther}
          className="rounded-md py-0.5 text-[12px] text-ink-2 enabled:hover:text-accent disabled:opacity-50"
        >
          다른 그림
        </button>
      )}
      <label
        className={`cursor-pointer rounded-md py-0.5 text-center text-[12px] text-ink-2 hover:text-accent ${disabled ? "pointer-events-none opacity-50" : ""}`}
      >
        내 사진
        <input
          type="file"
          accept=".jpg,.jpeg,.png,.webp,.mp4,.mov,.m4v,.webm"
          className="sr-only"
          disabled={disabled}
          onChange={(e) => {
            onOwn(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </label>
    </div>
  );
}

// ── ③ 완성 ───────────────────────────────────────────────

function FinishView({
  project,
  progress,
  act,
  onEdit,
}: {
  project: Project;
  progress: Partial<Record<StepId, StepProgress>>;
  act: (fn: () => Promise<unknown>) => Promise<void>;
  onEdit: () => void;
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
                <>
                  <ul className="mt-2 list-disc pl-5 text-[14px] text-ink-2">
                    {failed.map((c) => (
                      <li key={c.id}>{CHECK_EASY[c.id] ?? c.detail}</li>
                    ))}
                  </ul>
                  <div className="mt-2 flex flex-wrap gap-4 text-[14px] font-semibold text-accent">
                    {failed.some((c) => c.id !== "loudness") && (
                      <button type="button" onClick={onEdit}>
                        다듬기로 가서 고치기 →
                      </button>
                    )}
                    {failed.some((c) => c.id === "loudness") && (
                      <button type="button" onClick={make} disabled={project.busy}>
                        영상 다시 만들기
                      </button>
                    )}
                  </div>
                </>
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
