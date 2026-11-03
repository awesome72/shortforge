"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, eventsUrl } from "./api";
import type { PipelineEvent, Project, Quota, StepId } from "./types";

export interface StepProgress {
  stage: string;
  progress: number; // 지금 작업(stage) 안에서의 진행
  value: number; // 단계 전체 진행. 작업이 바뀌어도 뒤로 가지 않는다
  parts?: Record<string, number>; // 함께 도는 작업별 진행 (5단계: 그림·음성)
}

// 작업별 0~1을 단계 전체 값으로 합친다. 렌더는 클립·합성이 이어서, 5단계는 그림·음성이 함께 돈다
const stepValue = (step: StepId, stage: string, progress: number, parts: Record<string, number>) => {
  if (step === "s5") return ((parts.images ?? 0) + (parts.tts ?? 0)) / 2;
  if (step !== "s7") return progress;
  return stage === "clips" ? progress * 0.5 : stage === "compose" ? 0.5 + progress * 0.5 : progress;
};

/**
 * 프로젝트 상태 + SSE 진행 이벤트.
 * 단계 완료·오류·편집 이벤트가 오면 Project JSON을 다시 읽는다(짧게 묶어서 한 번).
 */
export function useProject(id: string, onEvent?: (e: PipelineEvent) => void, withQuota = false) {
  const [project, setProject] = useState<Project | null>(null);
  const [quota, setQuota] = useState<Quota | null>(null);
  const [progress, setProgress] = useState<Partial<Record<StepId, StepProgress>>>({});
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 화면 알림용. 구독을 다시 맺지 않도록 최신 콜백만 ref에 둔다
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  });

  const refresh = useCallback(async () => {
    try {
      setProject(await api.get(id));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    // 쿼터 미터는 전문가 화면에만 있다. 실패해도 프로젝트 화면을 막지 않는다
    if (withQuota) api.quota().then(setQuota, () => undefined);
  }, [id, withQuota]);

  const scheduleRefresh = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(refresh, 120);
  }, [refresh]);

  useEffect(() => {
    // 첫 로드. 이후 갱신은 SSE 이벤트가 이끈다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
    const es = new EventSource(eventsUrl(id));
    es.onopen = () => {
      setConnected(true);
      scheduleRefresh(); // 끊긴 사이에 끝난 일을 놓치지 않게
    };
    es.onerror = () => setConnected(false);
    const handle = (raw: MessageEvent) => {
      const e = JSON.parse(raw.data) as PipelineEvent;
      onEventRef.current?.(e);
      if (e.type === "step_started") {
        setProgress((p) => ({ ...p, [e.step]: { stage: "시작", progress: 0, value: 0 } }));
        scheduleRefresh();
      } else if (e.type === "step_progress") {
        setProgress((p) => {
          const parts = { ...p[e.step]?.parts, [e.stage]: e.progress };
          const value = Math.max(p[e.step]?.value ?? 0, stepValue(e.step, e.stage, e.progress, parts));
          return { ...p, [e.step]: { stage: e.stage, progress: e.progress, value, parts } };
        });
      } else {
        if (e.type === "step_done" || e.type === "step_error") {
          // 완료는 100%로 남긴다: 비우면 상태를 다시 읽기 전 잠깐 0%로 보였다. 다시 시작하면 지워진다
          setProgress((p) => {
            const last = p[e.step];
            return { ...p, [e.step]: e.type === "step_done" && last ? { ...last, value: 1 } : undefined };
          });
        }
        scheduleRefresh();
      }
    };
    const types = ["step_started", "step_progress", "step_done", "step_error", "run_finished", "run_failed", "run_cancelled", "edited", "motion_started", "motion_finished"];
    types.forEach((t) => es.addEventListener(t, handle));
    return () => {
      es.close();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [id, refresh, scheduleRefresh]);

  return { project, setProject, quota, progress, error, setError, connected, refresh };
}
