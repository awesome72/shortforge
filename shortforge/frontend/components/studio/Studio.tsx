"use client";

import Link from "next/link";
import { Fragment, useEffect, useRef, useState } from "react";
import { api, fileUrl, supportBundleUrl } from "@/lib/api";
import { clipPrice } from "@/lib/clip";
import { failureOf } from "@/lib/failure";
import { HEIC_ACCEPT, HEIC_HINT, isHeic } from "@/lib/photo";
import { freshKeywords } from "@/lib/recover";
import { FACTOR_LABEL, MARKET_LABEL, MOOD_LABEL, VISUAL_STYLE_LABEL } from "@/lib/labels";
import { STEP_IDS, type AppConfig, type Asset, type Input, type Project, type StepId } from "@/lib/types";
import { useNarrow } from "@/lib/useNarrow";
import { useProject, type StepProgress } from "@/lib/useProject";
import { Chips, ConfirmInline, motionConfirm } from "../Confirm";
import { Formula } from "../Formula";
import { Icon } from "../Icon";
import { StopButton } from "../StopButton";
import { ListingInfoEditor } from "./ListingInfoEditor";
import { ShopInfoEditor } from "./ShopInfoEditor";
import { TopicFix } from "./TopicFix";
import { SceneMedia, VideoPlayer, isVideo } from "../Media";
import { PublishChecklist } from "../PublishChecklist";
import { SetupNotice } from "../SetupNotice";
import { TimelinePreview } from "../TimelinePreview";
import { YouTubeModal } from "../YouTubeModal";
import { Brand, Button, Notice, ProgressBar } from "../ui";

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
  s2: "한국과 해외에서 잘 된 영상을 찾는 중",
  s3: "왜 잘 됐는지 살펴보는 중",
  s4: "대사와 장면을 쓰는 중",
  s5: "그림과 목소리를 만드는 중",
  s6: "장면 순서와 음악을 맞추는 중",
  s7: "영상을 완성하는 중",
};
// 남은 시간 어림에 쓰는 단계별 시간(초). 실제 키로 잰 값이고 s5는 실측 중앙값이다.
// 예상보다 많이 걸리면 '평소보다 오래 걸려요'로 바꿔 말한다
const STEP_SEC: Record<StepId, number> = { s1: 2, s2: 7, s3: 10, s4: 150, s5: 39, s6: 5, s7: 60 };
// 고급 모드는 대사를 유료 모델이 써서 훨씬 빠르다 (최근 10회 중앙값, 2026-11-01)
const STEP_SEC_ADVANCED: Record<StepId, number> = { ...STEP_SEC, s3: 18, s4: 42, s5: 25, s6: 7 };
// 실패 안내에 쓰는 이름 ("…에서 문제가 생겼어요")
const STEP_NAME: Record<StepId, string> = {
  s1: "주제 정리",
  s2: "참고 영상 찾기",
  s3: "잘 된 이유 살펴보기",
  s4: "대사 쓰기",
  s5: "그림·목소리 만들기",
  s6: "장면 순서·음악 맞추기",
  s7: "영상 완성하기",
};
const ROLE_EASY: Record<string, string> = {
  hook: "시작",
  problem: "고민",
  method: "방법",
  twist: "반전",
  reveal: "답 공개",
  offer: "혜택",
  payoff: "결과",
  cta: "마무리",
};
// 가게 홍보 영상의 장면 이름 (취미 영상과 뜻이 다른 것만)
const ROLE_SHOP: Record<string, string> = { method: "상품", payoff: "가게 자랑", cta: "손님이 할 일" };
const ROLE_LISTING: Record<string, string> = { method: "공간", payoff: "장점", offer: "가격", cta: "연락" };
const LOOK_OPTIONS = ["photo", "cinematic", "illustration", "watercolor"] as const;
// 영상으로 바꾸면 효과가 큰 장면 (시작과 반전·공개·결과). 나머지는 그림의 움직임으로 충분하다
const KEY_ROLES = new Set(["hook", "twist", "reveal", "offer", "payoff"]);
// 완성 점검 결과를 쉬운 말과 할 일로 (LUFS 같은 말을 보이지 않는다)
const CHECK_EASY: Record<string, string> = {
  duration: "목표보다 길거나 짧아요. 대사를 줄이거나 늘려 보세요.",
  loudness: "소리 크기가 조금 달라요. 다시 완성하면 대부분 맞춰져요.",
  silence: "소리가 끊기는 곳이 있어요. 어색하면 그 대사를 조금 바꿔 보세요.",
  caption_width: "화면보다 긴 자막이 있어요. 대사를 조금 짧게 해 주세요.",
};

const failureLink =
  "inline-flex min-h-9 items-center rounded-ctl border border-line-strong bg-card px-3.5 text-sm font-semibold text-ink no-underline hover:bg-surface";

export function Studio({ id }: { id: string }) {
  const [actionError, setActionError] = useState<string | null>(null);
  const { project, progress, error } = useProject(id, (e) => {
    // 영상 만들기는 몇 분 걸려, 새로고침한 화면도 실패 이유를 볼 수 있게 한다
    if (e.type === "motion_finished" && e.error) setActionError(e.error);
  });
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [view, setView] = useState<View | null>(null); // 사용자가 고른 화면 (없으면 진행에 맞춰)

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
      // 글자 대신 화면 모양의 뼈대
      <div className="mx-auto flex max-w-[1280px] flex-col gap-4 px-4 pt-24 sm:px-6" aria-busy="true" aria-label="불러오는 중">
        <div className="sf-skel h-9 w-2/5" />
        <div className="sf-skel h-24 w-full rounded-panel" />
        <div className="sf-skel h-24 w-full rounded-panel" />
        <div className="sf-skel h-24 w-full rounded-panel" />
      </div>
    );
  }

  const st = project.status;
  // 그림·목소리를 만들었으면 다듬을 수 있다(그림이 빈 장면은 다듬기에서 내 사진을 올린다)
  const editable = st.s6 === "done" || !!project.timeline || (st.s5 === "done" && !!project.assets);
  const auto: View = st.s7 === "running" || st.s7 === "done" ? "finish" : editable ? "edit" : "idea";
  const current = view ?? auto;
  const failed = STEP_IDS.find((s) => st[s] === "error");
  const failure = failed ? failureOf(project.error_kinds?.[failed]) : null;
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
    act(() => {
      if (failed !== "s7") return api.runAll(id, failed ?? "s1", "s6");
      const from = firstUndone(project);
      return from ? api.runAll(id, from, "s7") : api.runStep(id, "s7");
    });
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
                    className="flex items-center gap-2 rounded-full px-3 py-1.5 text-md text-muted enabled:hover:text-ink disabled:opacity-40 aria-[current=step]:bg-accent-tint aria-[current=step]:font-semibold aria-[current=step]:text-accent"
                  >
                    <span className="grid size-6 place-items-center rounded-full border border-current text-xs">
                      {v.n}
                    </span>
                    {v.label}
                  </button>
                </span>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-4 text-sm">
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
        <h1 className="text-xl leading-tight font-bold tracking-[-0.025em] sm:text-2xl">
          {project.input?.topic ?? "새 영상"}
        </h1>
        {project.input?.mode === "business" && <ShopInfoEditor project={project} act={act} />}
        {project.input?.mode === "listing" && <ListingInfoEditor project={project} act={act} />}

        {failed && !project.busy && (
          <div className="mt-5">
            {/* 사용자가 멈춘 것은 오류가 아니다 (차분한 안내로) */}
            <Notice tone={project.error_kinds?.[failed] === "cancelled" ? "warn" : "error"} live={false}>
              <div className="flex flex-wrap items-center gap-3">
                <span className="min-w-[220px] flex-1">
                  <span role="alert">
                    {failure?.text ??
                      `${STEP_NAME[failed]}에서 멈췄어요. 다시 시도해 보세요.`}
                  </span>
                  <details className="mt-1 text-xs opacity-80">
                    <summary className="cursor-pointer">자세히</summary>
                    {project.errors[failed]}
                    <span className="block">계속 안 되면 설정에서 키를 확인해 주세요.</span>
                    <a href={supportBundleUrl(id)} className="mt-1 block font-semibold underline">
                      문제 보고용 파일 받기
                    </a>
                    <span className="block">주제·대사(가게·사무소 정보 포함)가 들어가요. 키는 빠져요. 열어 보고 보내 주세요.</span>
                  </details>
                </span>
                {failure?.action === "photos" ? (
                  <label className="cursor-pointer rounded-ctl bg-accent px-4 py-2 text-sm font-semibold text-accent-ink focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent">
                    사진 올리기
                    <input
                      type="file"
                      multiple
                      accept={`.jpg,.jpeg,.png,.webp,${HEIC_ACCEPT}`}
                      className="sr-only"
                      onChange={(e) => {
                        const files = [...(e.target.files ?? [])];
                        if (files.some(isHeic)) {
                          setActionError(HEIC_HINT);
                          return;
                        }
                        if (files.length)
                          act(async () => {
                            // 종류 기본값 (매물은 거실, 가게는 메뉴)
                            await api.upload(id, files, true, files.map(() => (project.input?.mode === "listing" ? "living" : "menu")));
                            // 사진 종류가 바뀌면 대사(4단계)가 다시 필요하다. 5단계부터 하면 막혔다
                            await api.runAll(id, "s4", "s6");
                          });
                      }}
                    />
                  </label>
                ) : (
                  <>
                    {failure?.action === "settings" && (
                      <Link href="/settings" className={failureLink}>
                        설정 열기
                      </Link>
                    )}
                    {(failure?.action === "topic" || failure?.action === "keywords") &&
                      (project.input?.mode ?? "hobby") === "hobby" && (
                      <TopicFix project={project} act={act} />
                    )}
                    {failure?.action === "keywords" && project.input ? (
                      // 같은 검색어로 다시 시도하면 같은 빈 결과가 나온다(13번 연달아 실패한 일)
                      <Button
                        onClick={() =>
                          act(async () => {
                            await api.patch(id, "input", freshKeywords(project.input!));
                            await api.runAll(id, "s1", "s6");
                          })
                        }
                      >
                        검색어 바꿔 다시 찾기
                      </Button>
                    ) : (
                      <Button onClick={retry}>다시 시도</Button>
                    )}
                  </>
                )}
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
                    ? "목소리가 없는 장면이 있어요."
                    : canGenerate
                      ? "그림이 없는 장면이 있어요."
                      : config?.image_mode === "auto"
                        ? "그림이 없는 장면이 있어요. '내 사진 넣기'로 채우거나 설정에서 그림 키를 넣어 주세요."
                        : "그림이 없는 장면이 있어요. '내 사진 넣기'로 채우거나 설정에서 그림 방식을 켜 주세요."}
                </span>
                {canGenerate || !noImage ? (
                  <Button onClick={() => act(() => api.runAll(id, "s5", "s6"))}>
                    {noImage ? "빈 장면 채우기" : "빠진 목소리 만들기"}
                  </Button>
                ) : (
                  <Link href="/settings" className="font-semibold">
                    설정 열기
                  </Link>
                )}
                {current !== "edit" && !(current === "idea" && editable) && (
                  // 아이디어 화면은 다 끝나면 '다듬기로 가기' 주 버튼이 따로 있다
                  <button type="button" className="font-semibold text-accent" onClick={() => setView("edit")}>
                    다듬기로 가기
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

        {/* 화면이 바뀔 때 한 번 부드럽게 (줄임 모드에서는 꺼진다) */}
        <div key={current} className="sf-enter">
        {current === "idea" && <IdeaView
            project={project}
            progress={progress}
            fast={!!config?.advanced}
            editable={editable}
            onEdit={() => setView("edit")}
            onStart={(from) => act(() => api.runAll(id, from, "s6"))}
            onPick={(angle) =>
              act(async () => {
                await api.patch(id, "input", { ...(project.input as Input), concept_pick: angle });
                await api.runAll(id, "s4", "s6"); // 같은 후보에서 골라 대사부터 다시 쓴다
              })
            }
          />}
        {current === "edit" && (
          <EditView
            project={project}
            progress={progress}
            act={act}
            onFinish={finish}
            config={config}
            fast={!!config?.advanced}
          />
        )}
        {current === "finish" && (
          <FinishView project={project} progress={progress} act={act} onEdit={() => setView("edit")} />
        )}
        </div>
      </main>
    </div>
  );
}

/** 지금 무엇을 하고 있는지 쉬운 말로 */
function Working({
  project,
  progress,
  fast = false,
  overall = false,
  remain = false,
}: {
  project: Project;
  progress: Partial<Record<StepId, StepProgress>>;
  fast?: boolean; // 고급 모드: 남은 시간 어림이 다르다
  overall?: boolean; // 다듬기 전까지(1~6단계) 전체 진행과 남은 시간을 보여 준다
  remain?: boolean; // 지금 단계부터 6단계까지만 (다듬기에서 그림 느낌·목소리를 바꿀 때)
}) {
  const running = STEP_IDS.find((s) => project.status[s] === "running");
  const end = STEP_IDS.indexOf("s6");
  // remain: 이번 실행이 시작한 단계부터 센다 (5→6단계로 넘어갈 때 막대가 뒤로 가지 않게)
  const [startAt, setStartAt] = useState<StepId | null>(null);
  // 단계 사이에 잠깐 running이 없는 순간에는 지우지 않는다 (실행 전체가 끝날 때만)
  const from =
    !running || running === "s7"
      ? running === "s7" || !project.busy
        ? null
        : startAt
      : !startAt || STEP_IDS.indexOf(running) < STEP_IDS.indexOf(startAt)
        ? running
        : startAt;
  if (from !== startAt) setStartAt(from); // 렌더 중 상태 맞추기 (React가 허용하는 방식)
  const scope: StepId[] =
    !running || running === "s7" || !from
      ? []
      : overall
        ? STEP_IDS.slice(0, end + 1)
        : remain
          ? STEP_IDS.slice(STEP_IDS.indexOf(from), end + 1)
          : [];
  const waiting = scope.length > 0;
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
  const p = progress[running]?.value ?? 0;
  const sec = fast ? STEP_SEC_ADVANCED : STEP_SEC;
  let value = p;
  let left: string | null = null;
  if (waiting) {
    const steps = scope;
    const all = steps.reduce((t, s) => t + sec[s], 0);
    const rest = steps.reduce(
      (t, s) => t + (project.status[s] === "done" ? 0 : sec[s] * (s === running ? 1 - p : 1)),
      0,
    );
    // eslint-disable-next-line react-hooks/refs -- 틱이 돌기 전(0초)의 값이 시작 때의 예상이다
    if (elapsed === 0) expected.current = rest;
    // eslint-disable-next-line react-hooks/refs
    const slow = elapsed > Math.max(60, expected.current * 1.5);
    value = 1 - rest / all;
    left = slow
      ? "평소보다 오래 걸려요"
      : rest < 45
        ? "거의 다 됐어요"
        : `앞으로 ${Math.max(1, Math.round(rest / 60))}분쯤`;
  }
  return (
    <div className="flex flex-col gap-2 rounded-panel bg-surface shadow-panel px-5 py-4">
      <div className="flex items-center gap-2.5 text-md font-medium">
        <span className="sf-pulse size-2 rounded-full bg-accent" />
        {WORK[running]}…
        {left && <span className="ml-auto text-sm font-normal text-muted">{left}</span>}
        <StopButton id={project.id} className={left ? "" : "ml-auto"} />
      </div>
      <ProgressBar value={value} />
    </div>
  );
}

// ── ① 아이디어 ─────────────────────────────────────────────

function IdeaView({
  project,
  progress,
  fast,
  onStart,
  onPick,
  editable,
  onEdit,
}: {
  project: Project;
  progress: Partial<Record<StepId, StepProgress>>;
  fast: boolean; // 고급 모드: 남은 시간 어림이 다르다
  onStart: (from: StepId) => void;
  onPick: (angle: string) => void;
  editable: boolean; // 다듬기를 열 수 있다
  onEdit: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [armed, setArmed] = useState<string | null>(null); // 바꾸기를 한 번 누른 아이디어
  const refs = (project.refs ?? []).filter((r) => r.selected);
  const patterns = (project.factors ?? []).filter((f) => f.name === "format");
  const factors = (project.factors ?? []).filter((f) => f.name !== "format").slice(0, 4);
  // 아직 시작하지 않았거나 중간에 멈춘 프로젝트(예: 복제본): 남은 단계를 다듬기 직전까지 이어서
  const next = STEP_IDS.find((s) => project.status[s] !== "done");
  const failed = STEP_IDS.some((s) => project.status[s] === "error");
  const stuck = STEP_IDS.some((s) => project.not_ready?.[s]);
  const canGo =
    !project.busy && !failed && !stuck && !!next && STEP_IDS.indexOf(next) <= STEP_IDS.indexOf("s6");
  const fresh = STEP_IDS.every((s) => project.status[s] === "idle");
  const shown = refs.find((r) => r.video_id === open);
  // 다른 아이디어로 바꾸면 사라지는 것 (확인 상자에 개수로)
  const photos = (project.assets ?? []).filter((a) => a.image.source === "user").length;
  const clips = (project.assets ?? []).filter((a) => a.image.still).length;
  const worldSearch = (project.input?.world_keywords?.length ?? 0) > 0;

  return (
    <div className="mt-6 flex flex-col gap-8">
      <p className="text-md text-ink-2">
        {worldSearch ? "한국과 해외에서" : "요즘"} 잘 된 영상을 보고 대사를 써요.
      </p>
      {canGo && (
        <div>
          <Button className="min-h-12 px-6 text-md" onClick={() => onStart(next!)}>
            {fresh ? "만들기 시작" : "이어서 만들기"}
          </Button>
        </div>
      )}
      {editable && !project.busy && (
        // 다 끝났는데 다음에 누를 것이 보이지 않았다 (주 버튼 0개)
        <div>
          <Button className="min-h-12 px-6 text-md" onClick={onEdit}>
            다듬기로 가기 →
          </Button>
        </div>
      )}
      <Working project={project} progress={progress} fast={fast} overall />

      {project.strategy && (
        <section>
          <h2 className="text-xl font-bold">이렇게 말할 거예요</h2>
          <p className="mt-1 text-sm text-muted">다듬기에서 고칠 수 있어요.</p>
          {project.strategy.concept ? (
            <p className="mt-2 text-md leading-relaxed font-medium text-ink">{project.strategy.concept.angle}</p>
          ) : null}
          {project.strategy.differentiator && (
            <p className="mt-1 text-md leading-relaxed text-ink-2">{project.strategy.differentiator}</p>
          )}
          <ol className="mt-3 flex flex-col gap-2">
            {project.strategy.scenes.map((s, i) => (
              <li key={s.id} className="flex gap-3 rounded-panel bg-surface shadow-panel px-4 py-3">
                <span className="w-14 flex-none text-xs text-muted">
                  <b className="text-ink-2">장면 {i + 1}</b>
                  <br />
                  {ROLE_EASY[s.role] ?? ""}
                </span>
                <span className="text-md leading-relaxed text-ink">{s.line}</span>
              </li>
            ))}
          </ol>
          {(project.strategy.other_concepts?.length ?? 0) > 0 && (
            <div className="mt-4">
              <h3 className="text-md font-semibold">다른 아이디어</h3>
              <ul className="mt-2 flex flex-col gap-2">
                {project.strategy.other_concepts!.map((c) => (
                  <li
                    key={c.angle}
                    className="flex flex-wrap items-center gap-3 rounded-panel bg-surface shadow-panel px-4 py-3"
                  >
                    <span className="min-w-[200px] flex-1">
                      <span className="block text-md text-ink">{c.angle}</span>
                      <span className="block text-xs text-muted">첫 대사: {c.hook}</span>
                    </span>
                    <Button
                      variant="ghost"
                      disabled={project.busy || armed === c.angle}
                      onClick={() => (project.assets ? setArmed(c.angle) : onPick(c.angle))}
                    >
                      이 아이디어로 바꾸기
                    </Button>
                    {armed === c.angle && (
                      <div className="w-full">
                        <ConfirmInline
                          kind="lose"
                          question="이 아이디어로 대사를 다시 쓸까요?"
                          chips={[
                            { text: "고친 대사", tone: "lose" },
                            ...(photos ? [{ text: `올린 사진 ${photos}장`, tone: "lose" as const }] : []),
                            ...(clips ? [{ text: `AI로 움직인 장면 ${clips}개`, tone: "lose" as const }] : []),
                            "약 3분",
                          ]}
                          confirmLabel="버리고 다시 쓰기"
                          disabled={project.busy}
                          onConfirm={() => {
                            setArmed(null);
                            onPick(c.angle);
                          }}
                          onCancel={() => setArmed(null)}
                        />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {refs.length > 0 && (
        <section>
          <h2 className="text-xl font-bold">참고 영상</h2>
          <p className="mt-1 text-sm text-muted">
            눌러서 크게 볼 수 있어요.
            {worldSearch && !refs.some((r) => r.market) && " 맞는 해외 영상이 없어 한국 영상만 봤어요."}
          </p>
          <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            {refs.map((r) => (
              <button key={r.video_id} type="button" onClick={() => setOpen(r.video_id)} className="group flex flex-col gap-2 text-left">
                <span className="relative block aspect-[9/16] overflow-hidden rounded-panel border border-line-strong bg-sunken">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={r.thumbnail_url} alt="" loading="lazy" className="h-full w-full scale-[1.34] object-cover" />
                  <span className="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100">
                    <span className="rounded-full bg-black/60 px-3 py-1.5 text-sm text-white">크게 보기</span>
                  </span>
                </span>
                <span className="line-clamp-2 text-sm leading-snug text-ink">{r.title_ko || r.title}</span>
                {r.market && (
                  <span className="text-xs text-muted">{MARKET_LABEL[r.market] ?? r.market}에서 인기</span>
                )}
              </button>
            ))}
          </div>
        </section>
      )}

      {patterns.length > 0 && (
        <section>
          <h2 className="text-xl font-bold">찾아낸 영상 공식</h2>
          <p className="mt-1 text-sm text-muted">
            참고 영상에서 짐작한 공식이에요. 이 중 하나로 구성해요.
          </p>
          <ul className="mt-3 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {patterns.map((f, i) => (
              <li key={i} className="flex flex-col gap-2 rounded-panel bg-surface shadow-panel px-5 py-4">
                <p className="text-md leading-relaxed text-ink">{f.finding}</p>
                <Formula factor={f} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {factors.length > 0 && (
        <section>
          <h2 className="text-xl font-bold">잘 된 이유</h2>
          <ul className="mt-3 grid gap-3 md:grid-cols-2">
            {factors.map((f) => (
              <li key={f.name} className="rounded-panel bg-surface shadow-panel px-5 py-4">
                <div className="text-sm font-semibold text-accent">{FACTOR_LABEL[f.name].replace(/ \(.*\)/, "")}</div>
                <p className="mt-1 text-md leading-relaxed text-ink-2">{f.finding}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {shown && <YouTubeModal videoId={shown.video_id} title={shown.title_ko || shown.title} onClose={() => setOpen(null)} />}
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
  fast,
}: {
  project: Project;
  progress: Partial<Record<StepId, StepProgress>>;
  act: (fn: () => Promise<unknown>, keepError?: boolean) => Promise<void>;
  onFinish: () => void;
  config: AppConfig | null;
  fast: boolean;
}) {
  const narrow = useNarrow();
  const [focus, setFocus] = useState<string | null>(null);
  const [saving, setSaving] = useState<string[]>([]); // 저장 중이거나 저장을 기다리는 장면
  const [unsaved, setUnsaved] = useState<string[]>([]); // 저장하지 못한 장면
  const [picturing, setPicturing] = useState<string | null>(null);
  const [musicing, setMusicing] = useState(false); // 음악을 만드는 몇 초 동안 다시 누르지 않게
  const [moving, setMoving] = useState(false); // 그림을 영상으로 만드는 중 (몇 분 걸릴 수 있다)
  const [bulkAsk, setBulkAsk] = useState(false); // 주요 장면 묶음: 값을 보고 한 번 더 누른다
  const [askMove, setAskMove] = useState<string | null>(null); // 장면 하나를 움직이기 전 확인 (돈·외부 전송)
  const [sheet, setSheet] = useState<string | null>(null); // 휴대폰: 장면 그림을 누르면 아래에서 올라오는 도구
  const [previewOpen, setPreviewOpen] = useState(false); // 좁은 화면: 미리보기를 크게 연다
  const previewBtn = useRef<HTMLButtonElement>(null);
  const previewClose = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (previewOpen) previewClose.current?.focus();
    else if (wasOpen.current) previewBtn.current?.focus();
    wasOpen.current = previewOpen;
  }, [previewOpen]);
  useEffect(() => {
    if (!previewOpen && !sheet) return;
    const close = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setPreviewOpen(false);
      setSheet(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [previewOpen, sheet]);
  const [stopping, setStopping] = useState(false);
  const stop = useRef(false); // 묶음: 지금 장면까지만 만든다. 화면을 떠나도 다음 장면을 시작하지 않는다
  useEffect(
    () => () => {
      stop.current = true;
    },
    [],
  );
  const [restyle, setRestyle] = useState<Partial<Input> | null>(null); // 영상이 그림으로 돌아가는 변경
  const [finishing, setFinishing] = useState(false);
  const failedLines = useRef(new Set<string>()); // 저장하지 못한 장면: 옛 대사로 완성하지 않는다
  const left = useRef(false); // 저장을 기다리는 사이 화면을 떠났으면 완성을 시작하지 않는다
  useEffect(() => {
    left.current = false;
    return () => {
      left.current = true;
    };
  }, []);
  const queue = useRef<Promise<unknown>>(Promise.resolve()); // 서버는 한 번에 한 편집만 받는다
  const scenes = project.strategy?.scenes ?? [];
  const input = project.input as Input;
  const tl = project.timeline;
  const busy = project.busy || saving.length > 0 || picturing !== null || musicing;
  const pickMusic = (body: Parameters<typeof api.setMusic>[1]) => {
    setMusicing(true);
    act(() => api.setMusic(project.id, body)).finally(() => setMusicing(false));
  };
  // 대사 칸은 저장 중인 장면만 잠근다. busy는 대사 저장 중에도 참이라 단계 실행으로만 판단한다
  const generating = moving || !!project.motion_scene;
  // 4단계가 남긴 사실 경고 중 아직 대사·제목에 남아 있는 말만 보여 준다 (고치면 사라진다)
  const spoken = [...(project.strategy?.titles ?? []), ...scenes.map((s) => s.line)].join(" ").normalize("NFKC");
  // 서버가 지금 대사로 다시 본 말 목록 (다듬기에서 새로 쓴 말도 잡힌다). 경고 문구를 다시 읽지 않는다
  const factWords = (project.fact_words ?? []).filter((w) => spoken.includes(w.normalize("NFKC")));
  const has = (text: string, w: string) => text.normalize("NFKC").includes(w.normalize("NFKC"));
  // 장면 대사에 든 말은 그 장면 카드의 배지로 보인다 (E3). 제목에만 든 말만 위에 남긴다
  const titleWords = factWords.filter((w) => !scenes.some((s) => has(s.line, w)));
  const locked =
    STEP_IDS.some((s) => project.status[s] === "running") ||
    picturing !== null ||
    musicing ||
    !!project.motion_scene ||
    finishing; // 저장을 기다리는 동안 대사가 더 바뀌지 않게
  // 홍보 영상(가게·매물)은 실제 사진만 쓴다. 사진을 AI 영상으로 움직이는 것은 둘 다 된다(묻고 확인)
  const listing = project.input?.mode === "listing";
  const business = project.input?.mode === "business" || listing;
  const canGenerate = !!config?.can_generate && !business;
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
  const videoGen = config?.video_gen ?? null;
  // 그림이 있는 장면만 영상으로 만들 수 있다. 값은 서버와 같은 길이로 어림한다
  const sceneCost = (sceneId: string) => clipPrice(project, videoGen, sceneId);
  // 바뀐 내용을 반영하기 전의 낡은 그림에 돈을 쓰지 않게 5단계가 끝나 있을 때만
  // 가게 영상도 실제 사진을 움직이는 것은 된다(그림을 새로 그리지는 않는다)
  const canMove = (sceneId: string) =>
    !!videoGen &&
    project.status.s5 === "done" &&
    !!images[sceneId]?.path &&
    !isVideo(images[sceneId]?.path);
  const isMine = (sceneId: string) => images[sceneId]?.source === "user";
  // 내 사진은 외부 서버로 나가므로 묶음에 넣지 않고 장면별로 확인받는다
  const keyScenes = scenes.filter((s) => KEY_ROLES.has(s.role) && canMove(s.id) && !isMine(s.id)).map((s) => s.id);
  const free = !!videoGen?.free; // 호출당 요금이 없는 방식
  const keyPrice = free ? 0 : keyScenes.reduce((sum, id) => sum + sceneCost(id), 0);
  // 장면 하나를 움직이기 전 확인 (돈이 나가거나 내 사진이 밖으로 나갈 때). 묻지 않아도 되면 null
  const moveAsk = (sceneId: string, n: number) =>
    motionConfirm({ label: `장면 ${n}`, free, price: sceneCost(sceneId), mine: isMine(sceneId), mode: input.mode });
  const toVideo = (ids: string[], photoOk = false) =>
    act(async () => {
      setBulkAsk(false);
      setAskMove(null);
      setMoving(true);
      stop.current = false;
      try {
        for (const id of ids) {
          if (stop.current) break;
          setPicturing(id);
          setFocus(id);
          await queue.current;
          await api.sceneMotion(project.id, id, photoOk); // 한 장면씩: 실패하면 거기서 멈추고 비용도 멈춘다
        }
      } finally {
        setPicturing(null);
        setMoving(false);
        setStopping(false);
      }
    });
  // 그림에서 만든 영상은 그림 느낌을 바꾸면 새 그림으로 돌아간다 (내 사진을 움직인 영상은 남는다)
  const lostClips = scenes.filter((s) => images[s.id]?.still && images[s.id]?.still?.source !== "user").length;
  const ownPhoto = (sceneId: string, file: File | undefined) =>
    file &&
    (isHeic(file)
      ? act(async () => {
          throw new Error(HEIC_HINT); // 대사 저장을 기다리지 않고 고른 순간 알린다
        })
      : picture(sceneId, async () => {
      const { saved } = await api.upload(project.id, [file], false); // 1단계 사진 목록은 건드리지 않는다
      await api.setScenePhoto(project.id, sceneId, saved[0]);
    }));
  const target = input.duration_sec;
  const length = (tl?.scenes ?? []).reduce((t, s) => t + (typeof s.duration === "number" ? s.duration : 0), 0);

  // 그림체·목소리는 그림·음성을 새로 만들어야 해서, 고르면 바로 다시 만든다(따로 누를 버튼 없이)
  const remake = (patch: Partial<Input>) =>
    Object.entries(patch).every(([k, v]) => input[k as keyof Input] === v) ||
    act(async () => {
      await api.patch(project.id, "input", { ...input, ...patch });
      await api.runAll(project.id, "s5", "s6");
    });
  const finishAfterSave = async () => {
    setFinishing(true);
    // 기다리는 동안 저장이 더 붙을 수 있어 꼬리가 바뀌지 않을 때까지 본다
    for (let tail = null; tail !== queue.current; ) {
      tail = queue.current;
      await tail.catch(() => undefined);
    }
    setFinishing(false);
    if (!left.current && failedLines.current.size === 0) onFinish();
  };
  const saveLine = (sceneId: string, text: string) => {
    setSaving((s) => [...s, sceneId]);
    const run = () =>
      act(async () => {
        try {
          await api.setLine(project.id, sceneId, text); // 그 장면 음성만 다시 만들어 미리보기에 반영
          failedLines.current.delete(sceneId);
          setUnsaved((s) => s.filter((x) => x !== sceneId));
        } catch (e) {
          failedLines.current.add(sceneId);
          setUnsaved((s) => [...s, sceneId]);
          throw e;
        } finally {
          setSaving((s) => s.filter((x) => x !== sceneId));
        }
      }, true); // 앞 저장의 오류가 다음 저장 시작에 지워지지 않게
    queue.current = queue.current.then(run, run);
    return queue.current;
  };

  const sceneTools = (s: { id: string }, i: number, vertical = false) => (
    <SceneTools
      label={`장면 ${i + 1}`}
      vertical={vertical}
      disabled={locked} // 대사 저장 중에 잠그면 Tab으로 넘어온 커서가 사라진다
      canGenerate={canGenerate}
      onOther={() => otherPicture(s.id)}
      onOwn={(file) => ownPhoto(s.id, file)}
      price={canMove(s.id) ? (free ? 0 : sceneCost(s.id)) : null}
      onVideo={() => (moveAsk(s.id, i + 1) ? setAskMove(s.id) : toVideo([s.id]))}
      onRevert={images[s.id]?.still ? () => picture(s.id, () => api.revertSceneMotion(project.id, s.id)) : undefined}
      onDone={() => setSheet(null)}
    />
  );
  const sheetScene = scenes.findIndex((x) => x.id === sheet);
  const preview = tl ? (
    <div className="relative">
      <TimelinePreview
        projectId={project.id}
        timeline={tl}
        version={project.version}
        width={narrow ? 300 : 360}
        compact
        focus={focus}
      />
      {busy && (
        <div className="absolute inset-0 flex items-center justify-center rounded-panel bg-black/50 text-md text-white">
          {saving.length
            ? "목소리를 새로 만드는 중…"
            : generating
              ? "AI로 움직이는 중…"
              : picturing
                ? "그림을 바꾸는 중…"
                : musicing
                  ? "음악을 만드는 중…"
                  : "새로 만드는 중…"}
        </div>
      )}
    </div>
  ) : (
    <div className="sf-skel aspect-[9/16] w-[300px] rounded-panel" aria-hidden="true" />
  );

  return (
    <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_auto]">
      <div className="flex min-w-0 flex-col gap-5">
        <p className="text-md text-ink-2">
          고치면 미리보기에 바로 반영돼요.
          {listing && " 사진은 이 매물의 실제 사진만, 얼굴·우편물·차량 번호가 안 보이게 넣어 주세요."}
        </p>
        <Working project={project} progress={progress} fast={fast} remain />
        {titleWords.length > 0 && (
          <Notice tone="warn">
            제목에 {listing ? "매물" : "가게"} 정보에 없는 말: {titleWords.join(", ")}. 사실인지 확인해 주세요.
          </Notice>
        )}
        {changed && !project.busy && missing === 0 && (
          <Notice tone="warn">
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex-1">바뀐 내용이 아직 미리보기에 없어요.</span>
              <Button
                disabled={busy}
                onClick={() => act(() => api.runAll(project.id, project.status.s5 !== "done" ? "s5" : "s6", "s6"))}
              >
                바뀐 내용 적용 · 약 1분
              </Button>
            </div>
          </Notice>
        )}

        <section className="flex flex-col gap-2.5">
          <h2 className="text-xl font-bold">대사</h2>
          {generating && (
            <div className="flex flex-wrap items-center gap-3 rounded-panel bg-surface px-4 py-3 text-md text-ink-2 shadow-panel">
              <span className="min-w-[220px] flex-1">
                {stopping
                  ? "지금 장면까지만 움직이고 멈출게요."
                  : `AI로 움직이는 중이에요. 장면마다 ${free ? "30초쯤" : "몇 분"} 걸려요.`}
              </span>
              {moving && !stopping && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    stop.current = true;
                    setStopping(true);
                  }}
                >
                  이 장면까지만
                </Button>
              )}
            </div>
          )}
          {scenes.map((s, i) => (
            <Fragment key={`${s.id}-${s.line}`}>
            <LineEditor
              index={i + 1}
              role={(listing && ROLE_LISTING[s.role]) || (business && ROLE_SHOP[s.role]) || (ROLE_EASY[s.role] ?? "")}
              roleKey={roleKey(s.role)}
              focused={focus === s.id}
              fixed={
                // 입력값을 그대로 넣은 대사다. 여기서 바꾸면 말한 가격과 끝 화면·설명란이 달라진다
                business && (s.role === "offer" || s.role === "cta")
              }
              badges={[
                ...(business && (s.role === "offer" || s.role === "cta")
                  ? [
                      {
                        tone: "lock" as const,
                        text: `🔒 ${listing ? "매물" : "가게"} 정보 그대로`,
                        detail: `적은 정보로 만든 대사예요. 위의 '${listing ? "매물" : "가게"} 정보 고치기'에서 바꿔요.`,
                      },
                    ]
                  : []),
                ...factWords
                  .filter((w) => has(s.line, w))
                  .map((w) => ({
                    tone: "warn" as const,
                    text: `확인: ${w}`,
                    detail: `${listing ? "매물" : "가게"} 정보에 없는 말이에요. 사실인지 확인해 주세요.`,
                  })),
                ...(issuesOf(images[s.id]).length
                  ? [
                      {
                        tone: "warn" as const,
                        text: issuesOf(images[s.id]).join(" · "),
                        detail: "AI가 그림을 살펴본 결과예요. 괜찮으면 그대로 둬요.",
                      },
                    ]
                  : []),
                ...(images[s.id]?.still
                  ? [{ tone: "info" as const, text: "움직인 장면", detail: "다르면 '원래대로'를 눌러요." }]
                  : []),
              ]}
              line={s.line}
              saving={saving.includes(s.id)}
              failed={unsaved.includes(s.id)}
              disabled={locked || saving.includes(s.id)}
              onFocus={() => setFocus(s.id)}
              onSave={(text) => saveLine(s.id, text)}
              media={
                <ScenePicture
                  label={`장면 ${i + 1}`}
                  src={fileUrl(project.id, images[s.id]?.path, project.version)}
                  path={images[s.id]?.path}
                  source={images[s.id]?.source}
                  roleKey={roleKey(s.role)}
                  working={picturing === s.id || project.motion_scene === s.id}
                  moving={generating}
                  onOpen={() => {
                    setFocus(s.id);
                    setSheet(s.id);
                  }}
                />
              }
              tools={sceneTools(s, i)}
            />
            {askMove === s.id && canMove(s.id) && moveAsk(s.id, i + 1) && (
              <ConfirmInline
                {...moveAsk(s.id, i + 1)!}
                disabled={busy}
                onConfirm={() => toVideo([s.id], isMine(s.id))}
                onCancel={() => setAskMove(null)}
              />
            )}
            </Fragment>
          ))}
          {keyScenes.length > 0 && (
            // 대사를 먼저 보고 고르도록 목록 맨 아래에 둔다 (E3)
            <div className="flex flex-col gap-2 rounded-panel bg-surface px-4 py-3 shadow-panel">
              <div className="flex flex-wrap items-center gap-3">
                <span className="min-w-[220px] flex-1 text-md text-ink-2">
                  주요 장면 {keyScenes.length}개를 AI로 움직일 수 있어요.
                  <Chips
                    className="mt-1.5"
                    items={
                      free
                        ? ["무료", "장면당 30초쯤", { text: "그림이 외부 데모 서버로 가요", tone: "out" }]
                        : [{ text: `약 $${keyPrice.toFixed(2)}`, tone: "money" }, "장면당 몇 분"]
                    }
                  />
                  <span className="mt-1 block text-xs text-muted">내 사진 장면은 빠져요.</span>
                </span>
                <Button
                  variant="ghost"
                  disabled={busy || bulkAsk}
                  onClick={() => (free ? toVideo(keyScenes) : setBulkAsk(true))}
                >
                  <Icon name="sparkle" className="text-accent" />
                  주요 장면 {keyScenes.length}개 움직이기
                </Button>
              </div>
              {bulkAsk && (
                <ConfirmInline
                  kind="money"
                  question={`주요 장면 ${keyScenes.length}개를 AI로 움직일까요?`}
                  chips={[
                    { text: `약 $${keyPrice.toFixed(2)}`, tone: "money" },
                    "장면당 몇 분",
                    { text: "Hugging Face 크레딧", tone: "out" },
                    "장면 사이에서 멈출 수 있어요",
                  ]}
                  confirmLabel={`$${keyPrice.toFixed(2)} 쓰고 시작`}
                  disabled={busy}
                  onConfirm={() => toVideo(keyScenes)}
                  onCancel={() => setBulkAsk(false)}
                />
              )}
            </div>
          )}
        </section>

        <section className="grid gap-4 md:grid-cols-2">
          {!business && (
          <Choice label="그림 느낌" hint="고르면 바로 다시 그려요 · 약 40초">
            <StylePicker
              value={input.visual_style}
              disabled={busy}
              onChange={(v) =>
                v !== input.visual_style && lostClips > 0
                  ? setRestyle({ visual_style: v })
                  : remake({ visual_style: v })
              }
            />
            {restyle && (
              <ConfirmInline
                kind="lose"
                question="그림 느낌을 바꿀까요?"
                chips={[
                  { text: `AI로 움직인 장면 ${lostClips}개가 새 그림으로`, tone: "lose" },
                  ...(free ? [] : [{ text: "쓴 돈은 돌아오지 않아요", tone: "lose" as const }]),
                  "약 40초",
                ]}
                confirmLabel={`바꾸고 ${lostClips}개 버리기`}
                disabled={busy}
                onConfirm={() => {
                  const patch = restyle;
                  setRestyle(null);
                  remake(patch);
                }}
                onCancel={() => setRestyle(null)}
              />
            )}
          </Choice>
          )}
          <Choice label="목소리" hint="▶로 들어 보고 고르세요 · 바꾸면 약 40초" wide={business}>
            <VoicePicker value={input.voice} disabled={busy} onChange={(v) => remake({ voice: v })} />
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
                    onClick={() => pickMusic({ mood })}
                    className={PILL}
                  >
                    {label}
                  </button>
                ))}
                <button
                  type="button"
                  disabled={busy}
                  aria-pressed={!tl.audio.bgm}
                  onClick={() => pickMusic({ off: true })}
                  className={PILL}
                >
                  음악 없음
                </button>
              </div>
            </Choice>
          )}
        </section>

        {/* 완성 버튼은 늘 화면 아래에 (장면이 많으면 1,900px 아래에 있었다) */}
        <div className="sticky bottom-0 z-20 -mx-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line bg-canvas/90 px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] backdrop-blur sm:-mx-6 sm:px-6 lg:mx-0 lg:px-0">
          <LengthMeter length={length} target={target} />
          {tl && (
            <Button ref={previewBtn} variant="ghost" className="lg:hidden" onClick={() => setPreviewOpen(true)}>
              <Icon name="play" size={14} />
              미리보기
            </Button>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <span className={`text-sm ${unsaved.length ? "text-err" : "text-muted"}`}>
              {unsaved.length ? "저장 안 된 대사가 있어요 · 빨간 배지를 눌러 다시 저장" : "1~2분쯤 걸려요"}
            </span>
            <Button
              className="min-h-12 px-6 text-md"
              // 대사 칸을 벗어나며 누르면 저장이 먼저 시작된다: 그 클릭을 버리지 않고 저장 뒤에 시작한다
              disabled={(busy && saving.length === 0) || changed || finishing || picturing !== null}
              onClick={finishAfterSave}
            >
              {finishing ? "대사 저장 뒤 시작해요…" : "영상 완성하기 →"}
            </Button>
          </div>
        </div>
      </div>

      <aside className="hidden flex-col items-center gap-3 lg:sticky lg:top-24 lg:flex lg:self-start">
        {preview}
        <p className="max-w-[360px] text-center text-xs text-muted">미리보기 · 완성본은 자막·음악이 더 매끄러워요</p>
      </aside>

      {/* 좁은 화면: 미리보기를 크게 */}
      {previewOpen && tl && (
        <div
          className="sf-enter fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-black/80 p-4 backdrop-blur-sm lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="미리보기"
        >
          {preview}
          <Button ref={previewClose} variant="ghost" onClick={() => setPreviewOpen(false)}>
            <Icon name="close" size={14} />
            닫기
          </Button>
        </div>
      )}
      {/* 휴대폰: 장면 그림을 누르면 그 장면 도구가 아래에서 올라온다 */}
      {sheet && sheetScene >= 0 && (
        <div className="fixed inset-0 z-50 sm:hidden" role="dialog" aria-modal="true" aria-label={`장면 ${sheetScene + 1} 도구`}>
          <button type="button" aria-label="닫기" className="absolute inset-0 bg-black/60" onClick={() => setSheet(null)} />
          <div className="sf-enter absolute inset-x-0 bottom-0 flex flex-col gap-1 rounded-t-[22px] bg-overlay px-4 pt-2 pb-[calc(1rem+env(safe-area-inset-bottom,0px))] shadow-pop">
            <span className="mx-auto mb-2 h-1 w-9 rounded-full bg-line-strong" aria-hidden="true" />
            <p className="px-1 pb-1 text-sm text-muted">장면 {sheetScene + 1}</p>
            {sceneTools(scenes[sheetScene], sheetScene, true)}
          </div>
        </div>
      )}
    </div>
  );
}

function Choice({
  label,
  hint,
  wide = false,
  children,
}: {
  label: string;
  hint?: string; // 고르면 무엇이 일어나는지 (예: 바로 다시 만든다)
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={`flex min-w-0 flex-col gap-2 ${wide ? "md:col-span-2" : ""}`}>
      <span className="flex flex-wrap items-baseline gap-x-2 text-md font-semibold">
        {label}
        {hint && <span className="text-xs font-normal text-muted">{hint}</span>}
      </span>
      {children}
    </div>
  );
}

const PILL =
  "rounded-full bg-card px-3.5 py-1.5 text-sm text-ink-2 enabled:hover:text-ink disabled:opacity-50 aria-pressed:bg-accent-tint aria-pressed:text-accent aria-pressed:shadow-[inset_0_0_0_1px_var(--color-accent)]";

/** 영상 길이 미터: 지금 길이와 목표를 막대 하나로 (목표 ±15%를 벗어나면 경고 색) */
function LengthMeter({ length, target }: { length: number; target: number }) {
  if (!length) return <span className="flex-1" />;
  const max = target * 1.25;
  const off = Math.abs(length - target) > target * 0.15;
  return (
    <div className="flex min-w-[220px] flex-1 items-center gap-2.5 text-xs text-ink-2 tabular-nums">
      <span>{Math.round(length)}초</span>
      <span
        role="meter"
        aria-label="영상 길이"
        aria-valuemin={0}
        aria-valuemax={Math.round(max)}
        aria-valuenow={Math.round(length)}
        className="relative h-1.5 flex-1 rounded-full bg-card"
      >
        <span
          className={`absolute inset-y-0 left-0 rounded-full transition-[width] duration-300 ${off ? "bg-stale" : "bg-ok"}`}
          style={{ width: `${Math.min(length / max, 1) * 100}%` }}
        />
        <span className="absolute -inset-y-1 w-0.5 rounded-full bg-ink-2" style={{ left: `${(target / max) * 100}%` }} />
      </span>
      <span className={off ? "text-stale" : "text-muted"}>
        목표 {target}초
        {length > target * 1.15 ? " · 조금 줄여 주세요" : length < target * 0.85 ? " · 조금 늘려도 좋아요" : ""}
      </span>
    </div>
  );
}

// 장면 역할 → 역할 색 (카드 왼쪽 선·역할 이름·빈 그림 자리). 전문가 화면과 같은 색
type RoleKey = "hook" | "problem" | "method" | "payoff" | "cta";
function roleKey(role: string): RoleKey {
  if (role === "hook" || role === "problem" || role === "method" || role === "cta") return role;
  if (role === "offer") return "cta";
  if (role === "twist" || role === "reveal" || role === "payoff") return "payoff";
  return "method";
}
const ROLE_BAR: Record<RoleKey, string> = {
  hook: "bg-role-hook",
  problem: "bg-role-problem",
  method: "bg-role-method",
  payoff: "bg-role-payoff",
  cta: "bg-role-cta",
};
const ROLE_TEXT: Record<RoleKey, string> = {
  hook: "text-role-hook",
  problem: "text-role-problem",
  method: "text-role-method",
  payoff: "text-role-payoff",
  cta: "text-role-cta",
};

/** 그림 느낌: 이름 대신 견본 그림을 보고 고른다 (public/samples/style-*.webp, 없으면 색 견본) */
function StylePicker({
  value,
  disabled,
  onChange,
}: {
  value: Input["visual_style"];
  disabled: boolean;
  onChange: (v: Input["visual_style"]) => void;
}) {
  return (
    <div role="group" aria-label="그림 느낌" className="flex flex-wrap gap-2.5">
      {(["auto", ...LOOK_OPTIONS] as const).map((v) => (
        <button
          key={v}
          type="button"
          disabled={disabled}
          aria-pressed={value === v}
          onClick={() => onChange(v)}
          className="group flex w-[58px] flex-col items-center gap-1.5 text-xs text-ink-2 disabled:opacity-50 aria-pressed:text-accent"
        >
          <span
            className="block aspect-[3/4] w-full rounded-ctl bg-card bg-cover bg-center shadow-panel transition-shadow group-aria-pressed:shadow-[0_0_0_2px_var(--color-accent)]"
            style={{
              backgroundImage:
                v === "auto"
                  ? "conic-gradient(from 210deg, var(--color-role-hook), var(--color-role-problem), var(--color-role-method), var(--color-role-payoff), var(--color-role-hook))"
                  : `url(/samples/style-${v}.webp), linear-gradient(160deg, var(--color-overlay), var(--color-sunken))`,
            }}
            aria-hidden="true"
          />
          {VISUAL_STYLE_LABEL[v]}
        </button>
      ))}
    </div>
  );
}

/** 목소리: 고르기 전에 ▶로 들어 본다 (public/samples/voice-*.mp3, 실제 합성 목소리) */
function VoicePicker({
  value,
  disabled,
  onChange,
}: {
  value: Input["voice"];
  disabled: boolean;
  onChange: (v: Input["voice"]) => void;
}) {
  const player = useRef<HTMLAudioElement | null>(null);
  const listen = (v: "female" | "male") => {
    player.current?.pause();
    player.current = new Audio(`/samples/voice-${v}.mp3`);
    player.current.play().catch(() => undefined);
  };
  useEffect(() => () => player.current?.pause(), []);
  const opts = [
    { value: "auto" as const, label: "자동" },
    { value: "female" as const, label: "여성" },
    { value: "male" as const, label: "남성" },
  ];
  return (
    <div role="group" aria-label="목소리" className="flex flex-wrap gap-1.5">
      {opts.map((o) => (
        <span key={o.value} className="flex items-center">
          <button
            type="button"
            disabled={disabled}
            aria-pressed={value === o.value}
            onClick={() => onChange(o.value)}
            className={`${PILL} ${o.value !== "auto" ? "rounded-r-none pr-2.5" : ""}`}
          >
            {o.label}
          </button>
          {o.value !== "auto" && (
            <button
              type="button"
              aria-label={`${o.label} 목소리 들어 보기`}
              onClick={() => listen(o.value as "female" | "male")}
              className="grid h-full min-h-8 place-items-center rounded-r-full bg-card pr-3 pl-1.5 text-muted hover:text-ink"
            >
              <Icon name="play" size={12} />
            </button>
          )}
        </span>
      ))}
    </div>
  );
}

/** 장면 대사 한 줄: 다 고치고 칸을 벗어나면 그 장면 목소리만 새로 만든다 */
type Badge = { tone: "lock" | "warn" | "err" | "info" | "accent"; text: string; detail?: string };
const BADGE: Record<Badge["tone"], string> = {
  lock: "bg-card text-ink-2",
  warn: "bg-stale-tint text-stale",
  err: "bg-err-tint text-err",
  info: "bg-info-tint text-info",
  accent: "bg-accent-tint text-accent",
};

function LineEditor({
  index,
  role,
  roleKey: rk,
  focused,
  line,
  saving,
  failed,
  disabled,
  onFocus,
  onSave,
  media,
  tools,
  fixed = false,
  badges = [],
}: {
  index: number;
  role: string;
  roleKey: RoleKey;
  focused: boolean; // 미리보기가 보여 주는 장면
  line: string;
  fixed?: boolean; // 입력값 그대로라 여기서 고칠 수 없는 대사
  badges?: Badge[]; // 이 장면에만 해당하는 상태 (위쪽 안내 대신 카드 안에)
  saving: boolean;
  failed: boolean;
  disabled: boolean;
  onFocus: () => void;
  onSave: (text: string) => void;
  media?: React.ReactNode;
  tools?: React.ReactNode; // 대사 아래 한 줄 도구 (휴대폰은 그림을 누르면 시트)
}) {
  const [draft, setDraft] = useState(line);
  const [openBadge, setOpenBadge] = useState<string | null>(null);
  const all: Badge[] = [
    ...badges,
    ...(saving ? [{ tone: "accent" as const, text: "목소리 만드는 중…" }] : []),
    ...(failed && !saving
      ? [{ tone: "err" as const, text: "저장 안 됨 · 다시 저장", detail: "누르면 지금 대사로 다시 저장해요." }]
      : []),
  ];
  const opened = all.find((b) => b.text === openBadge && b.detail);
  return (
    <div
      className={`grid grid-cols-[4px_64px_minmax(0,1fr)] gap-3 rounded-panel bg-surface py-3 pr-3.5 transition-shadow focus-within:shadow-[0_0_0_1.5px_var(--color-accent)] sm:grid-cols-[4px_84px_minmax(0,1fr)] sm:gap-3.5 ${focused ? "shadow-[0_0_0_1px_var(--color-line-strong),var(--shadow-panel)]" : "shadow-panel"}`}
    >
      <span className={`rounded-r ${ROLE_BAR[rk]}`} aria-hidden="true" />
      {media}
      <div className="flex min-w-0 flex-col gap-1.5">
        <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <b className="font-semibold text-ink-2">장면 {index}</b>
          <span className={ROLE_TEXT[rk]}>● {role}</span>
          {all.map((b) =>
            b.tone === "err" || b.detail ? (
              <button
                key={b.text}
                type="button"
                disabled={b.tone === "err" && (disabled || saving)}
                aria-expanded={b.detail && b.tone !== "err" ? openBadge === b.text : undefined}
                onClick={() => {
                  if (b.tone === "err") onSave(draft.trim() || line); // 저장 실패: 그 자리에서 다시 저장
                  else setOpenBadge((o) => (o === b.text ? null : b.text));
                }}
                className={`rounded-md px-1.5 py-px text-2xs disabled:opacity-50 ${BADGE[b.tone]}`}
              >
                {b.text}
              </button>
            ) : (
              // 누를 일이 없는 상태 표시는 버튼으로 그리지 않는다
              <span key={b.text} className={`rounded-md px-1.5 py-px text-2xs ${BADGE[b.tone]}`}>
                {b.text}
              </span>
            ),
          )}
        </span>
        {opened && <span className="text-xs text-muted">{opened.detail}</span>}
        <label className="sr-only" htmlFor={`line-${index}`}>
          장면 {index} 대사
        </label>
        <textarea
          id={`line-${index}`}
          rows={Math.min(4, Math.max(1, Math.ceil(draft.length / 34)))}
          value={draft}
          disabled={disabled}
          readOnly={fixed}
          maxLength={200}
          onFocus={onFocus}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            if (!draft.trim()) setDraft(line); // 비우면 원래 대사로
            else if (draft.trim() !== line.trim()) onSave(draft.trim());
          }}
          className="resize-none bg-transparent text-lg leading-normal text-ink outline-none read-only:text-ink-2 disabled:opacity-60"
        />
        <div className="hidden sm:block">{tools}</div>
      </div>
    </div>
  );
}

const ISSUE_LABEL: Record<string, string> = {
  text: "글자가 보여요",
  distorted: "모양이 어색해요",
  other_person: "다른 사람 같아요",
};

/** AI 그림 점검 결과 (지금 그림을 본 결과일 때만) */
function issuesOf(image: Asset["image"] | undefined): string[] {
  const check = image?.check;
  if (!image || !check || check.path !== image.path) return [];
  return check.issues.map((k) => ISSUE_LABEL[k] ?? k);
}

const SOURCE_TAG: Record<string, string> = { generated: "AI", stock: "무료 사진", user: "내 사진" };

/** 장면 그림 한 장 (휴대폰에서는 누르면 그 장면 도구가 올라온다) */
function ScenePicture({
  label,
  src,
  path,
  source,
  roleKey: rk,
  working,
  moving,
  onOpen,
}: {
  label: string; // "장면 2" (화면 낭독기가 버튼을 구분하게)
  src: string | null;
  path?: string | null;
  source?: string;
  roleKey: RoleKey;
  working: boolean;
  moving: boolean;
  onOpen: () => void;
}) {
  const body = (
    <span className="relative block aspect-[9/16] w-full overflow-hidden rounded-ctl bg-sunken">
      {src ? (
        <SceneMedia src={src} path={path} className="h-full w-full object-cover" />
      ) : (
        // 깨진 그림 아이콘 대신 역할 색 자리
        <span
          className="flex h-full items-center justify-center px-1 text-center text-2xs text-ink-2"
          style={{
            background: `linear-gradient(170deg, color-mix(in srgb, var(--color-role-${rk}) 32%, var(--color-card)), var(--color-sunken))`,
          }}
        >
          그림 없음
        </span>
      )}
      {src && source && SOURCE_TAG[source] && (
        <span className="absolute top-1 left-1 rounded-md bg-black/55 px-1 text-2xs leading-4 text-white">
          {SOURCE_TAG[source]}
        </span>
      )}
      {working && (
        <span className="absolute inset-0 flex items-center justify-center bg-black/55 text-2xs text-white">
          {moving ? "만드는 중…" : "바꾸는 중…"}
        </span>
      )}
    </span>
  );
  return (
    <>
      <span className="hidden self-start sm:block">{body}</span>
      <button type="button" className="self-start sm:hidden" aria-label={`${label} 그림 도구 열기`} onClick={onOpen}>
        {body}
      </button>
    </>
  );
}

/** 장면 그림 도구: 다른 그림 · 내 사진 넣기 · AI로 움직이기 · 원래대로 (한 줄, 휴대폰 시트에서는 세로) */
function SceneTools({
  label,
  vertical,
  disabled,
  canGenerate,
  onOther,
  onOwn,
  price,
  onVideo,
  onRevert,
  onDone,
}: {
  label: string;
  vertical: boolean;
  disabled: boolean;
  canGenerate: boolean;
  onOther: () => void;
  onOwn: (file: File | undefined) => void;
  price: number | null; // 영상으로 바꿀 수 있으면 값 (0은 호출당 요금 없음)
  onVideo: () => void;
  onRevert?: () => void; // 그림을 움직여 만든 영상이면 원래 그림으로
  onDone: () => void; // 시트를 닫는다
}) {
  const tool = vertical
    ? "flex min-h-12 w-full items-center gap-3 rounded-ctl px-3 text-md text-ink enabled:hover:bg-card disabled:opacity-50"
    : "inline-flex min-h-8 items-center gap-1.5 rounded-ctl px-2 text-sm text-ink-2 enabled:hover:bg-card enabled:hover:text-ink disabled:opacity-50";
  const run = (fn: () => void) => () => {
    fn();
    onDone();
  };
  return (
    <div className={vertical ? "flex flex-col" : "-ml-2 flex flex-wrap items-center gap-0.5"}>
      {onRevert && (
        <button type="button" disabled={disabled} onClick={run(onRevert)} aria-label={`${label} 원래대로`} className={tool}>
          <Icon name="undo" />
          원래대로
        </button>
      )}
      {canGenerate && !onRevert && (
        <button type="button" disabled={disabled} onClick={run(onOther)} aria-label={`${label} 다른 그림`} className={tool}>
          <Icon name="refresh" />
          다른 그림
        </button>
      )}
      <label
        aria-label={`${label} 내 사진 넣기`}
        className={`${tool} cursor-pointer focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent ${disabled ? "pointer-events-none opacity-50" : ""}`}
      >
        <Icon name="upload" />
        내 사진 넣기
        <input
          type="file"
          accept={`.jpg,.jpeg,.png,.webp,.mp4,.mov,.m4v,.webm,${HEIC_ACCEPT}`}
          className="sr-only"
          disabled={disabled}
          onChange={(e) => {
            onOwn(e.target.files?.[0]);
            e.target.value = "";
            onDone();
          }}
        />
      </label>
      {price !== null && (
        <button
          type="button"
          disabled={disabled}
          onClick={run(onVideo)}
          aria-label={`${label} AI로 움직이기`}
          className={`${tool} text-accent enabled:hover:text-accent-strong`}
        >
          <Icon name="sparkle" />
          AI로 움직이기
          {/* 돈·외부 전송은 툴팁에만 두지 않는다 (휴대폰에서 보이지 않는다) */}
          <span className={`text-xs tabular-nums ${vertical ? "ml-auto" : ""} text-muted`}>
            {price > 0 ? `$${price.toFixed(2)}` : "무료 · 외부 전송"}
          </span>
        </button>
      )}
    </div>
  );
}

// ── ③ 완성 ───────────────────────────────────────────────

/** 7단계 앞에서 아직 done이 아닌 첫 단계. 7단계만 부르면 '앞 단계를 먼저' 409였다 */
function firstUndone(project: Project): StepId | undefined {
  return STEP_IDS.filter((s) => s !== "s7").find((s) => project.status[s] !== "done");
}

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
  const stale = project.status.s7 === "stale" && !!r;
  // 다시 만들다 실패·멈춤이어도 지난 완성본은 그대로 있다(합성은 임시 파일에 하고 성공해야 바꾼다)
  const errored = project.status.s7 === "error" && !!r;
  const previous = stale || errored;
  const shown = (done || previous) && r;
  const video = shown ? fileUrl(project.id, r.path, project.version) : null;
  const failed = shown ? r.checks.filter((c) => !c.ok) : [];
  // 앞 단계가 남아 있으면 거기부터 이어서 (7단계만 부르면 '앞 단계를 먼저' 409였다)
  const from = firstUndone(project);
  const make = () => act(() => (from ? api.runAll(project.id, from, "s7") : api.runStep(project.id, "s7")));
  // 10-29 이전 음성: 말 길이 기록이 없어 대사 사이가 비었다. 6단계를 다시 하면 맞춰진다
  const oldVoices = (project.assets ?? []).some((a) => a.voice.speech_sec == null && a.voice.words_path);

  return (
    <div className="mt-6 grid gap-8 lg:grid-cols-[auto_minmax(0,1fr)]">
      <div className="flex flex-col items-center gap-3">
        {video ? (
          // 실제로 올렸을 때처럼 휴대폰 틀 안에서 본다
          <VideoPlayer
            key={video}
            src={video}
            className="aspect-[9/16] rounded-[24px] shadow-[0_0_0_6px_var(--color-sunken),0_0_0_7px_var(--color-line-strong),var(--shadow-pop)]"
            style={{ width: narrow ? 300 : 380 }}
          />
        ) : (
          <div
            className="flex aspect-[9/16] flex-col items-center justify-center gap-3 rounded-panel border border-line-strong bg-surface p-8 text-center text-md text-muted"
            style={{ width: narrow ? 300 : 380 }}
          >
            {running ? (
              <>
                <span className="sf-pulse size-2.5 rounded-full bg-accent" />
                영상을 완성하는 중… {Math.round((progress.s7?.value ?? 0) * 100)}%
                <span className="text-sm">1~2분쯤 걸려요</span>
                <StopButton id={project.id} />
              </>
            ) : (
              <>
                아직 완성하지 않았어요
                <Button className="min-h-12 px-6 text-md" onClick={make} disabled={project.busy}>
                  영상 완성하기
                </Button>
                <span className="text-sm">그림·목소리·자막·음악을 한 편으로 합쳐요 · 1~2분</span>
              </>
            )}
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-col gap-5">
        {stale && !running && (
          <Notice tone="warn">
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex-1">바꾼 내용이 아직 영상에 없어요.</span>
              <Button onClick={make} disabled={project.busy}>
                다시 완성 · 1~2분
              </Button>
            </div>
          </Notice>
        )}
        {shown ? (
          <>
            <div
              className={`flex flex-col gap-1 rounded-panel px-5 py-4 shadow-panel ${!previous && failed.length === 0 ? "bg-surface bg-[linear-gradient(160deg,var(--color-ok-tint),transparent_55%)] ring-1 ring-ok/25" : "bg-surface"}`}
            >
              {!previous && failed.length === 0 && (
                <span className="flex w-fit items-center gap-1 rounded-full bg-ok-tint px-2.5 py-0.5 text-xs text-ok">
                  <Icon name="check" size={12} />
                  자동 점검 통과
                </span>
              )}
              <div className="text-xl font-bold">
                {previous
                  ? errored
                    ? "지난 영상이에요. 다시 완성하다 멈췄어요"
                    : "지난 영상이에요"
                  : failed.length === 0
                  ? "영상이 완성됐어요"
                  : failed.length === 1
                    ? "거의 다 됐어요. 한 가지만 확인해 주세요"
                    : `거의 다 됐어요. ${failed.length}가지를 확인해 주세요`}
              </div>
              {failed.length > 0 ? (
                <>
                  <ul className="mt-2 list-disc pl-5 text-md text-ink-2">
                    {failed.map((c) => (
                      <li key={c.id}>{CHECK_EASY[c.id] ?? c.detail}</li>
                    ))}
                  </ul>
                  <div className="mt-2 flex flex-wrap gap-4 text-md font-semibold text-accent">
                    {failed.some((c) => c.id !== "loudness") && (
                      <button type="button" onClick={onEdit}>
                        다듬기로 가서 고치기 →
                      </button>
                    )}
                    {failed.some((c) => c.id === "loudness") && (
                      <button type="button" onClick={make} disabled={project.busy}>
                        다시 완성하기
                      </button>
                    )}
                    {failed.some((c) => c.id === "silence") && oldVoices && (
                      // 예전 음성은 말 길이 기록이 없어 대사 사이가 비었다. 6단계를 다시 하면 맞춰진다(AI 호출 없음)
                      <button
                        type="button"
                        onClick={() => act(() => api.runAll(project.id, "s6", "s7"))}
                        disabled={project.busy}
                      >
                        대사 사이 맞추고 다시 완성
                      </button>
                    )}
                  </div>
                </>
              ) : (
                <p className="mt-1 text-md text-muted">
                  {previous
                    ? errored
                      ? "지난 영상은 자동 점검(길이·소리·자막)을 통과했어요."
                      : "지난 영상은 자동 점검(길이·소리·자막)을 통과했어요."
                    : "길이·소리 크기·무음·자막 폭을 자동으로 확인했어요."}
                </p>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <a
                  href={fileUrl(project.id, r.path, project.version, true) ?? undefined}
                  className="inline-flex min-h-12 items-center gap-2 rounded-ctl bg-accent px-6 text-md font-semibold text-accent-ink no-underline hover:bg-accent-strong hover:text-accent-ink"
                >
                  <Icon name="download" />
                  영상 내려받기
                </a>
                <a
                  href={fileUrl(project.id, r.srt, project.version, true) ?? undefined}
                  className="inline-flex min-h-12 items-center rounded-ctl border border-line-strong px-5 text-md text-ink no-underline hover:bg-card hover:text-ink"
                >
                  자막 받기 (.srt)
                </a>
                {project.render_outdated && (
                  <Button variant="ghost" className="min-h-12" disabled={project.busy} onClick={make}>
                    최신 품질로 다시 완성
                  </Button>
                )}
              </div>
            </div>
            <PublishChecklist projectId={project.id} version={project.version} />
          </>
        ) : null}
      </div>
    </div>
  );
}
