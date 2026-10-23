"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, eventsUrl } from "./api";
import type { PipelineEvent, Project, Quota, StepId } from "./types";

export interface StepProgress {
  stage: string;
  progress: number;
}

/**
 * 프로젝트 상태 + SSE 진행 이벤트.
 * 단계 완료·오류·편집 이벤트가 오면 Project JSON을 다시 읽는다(짧게 묶어서 한 번).
 */
export function useProject(id: string, onEvent?: (e: PipelineEvent) => void) {
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
      const [p, q] = await Promise.all([api.get(id), api.quota()]);
      setProject(p);
      setQuota(q);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  const scheduleRefresh = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(refresh, 120);
  }, [refresh]);

  useEffect(() => {
    // 첫 로드. 이후 갱신은 SSE 이벤트가 이끈다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
    const es = new EventSource(eventsUrl(id));
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    const handle = (raw: MessageEvent) => {
      const e = JSON.parse(raw.data) as PipelineEvent;
      onEventRef.current?.(e);
      if (e.type === "step_started") {
        setProgress((p) => ({ ...p, [e.step]: { stage: "시작", progress: 0 } }));
        scheduleRefresh();
      } else if (e.type === "step_progress") {
        setProgress((p) => ({ ...p, [e.step]: { stage: e.stage, progress: e.progress } }));
      } else {
        if (e.type === "step_done" || e.type === "step_error") {
          setProgress((p) => ({ ...p, [e.step]: undefined }));
        }
        scheduleRefresh();
      }
    };
    const types = ["step_started", "step_progress", "step_done", "step_error", "run_finished", "run_failed", "edited"];
    types.forEach((t) => es.addEventListener(t, handle));
    return () => {
      es.close();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [id, refresh, scheduleRefresh]);

  return { project, setProject, quota, progress, error, setError, connected, refresh };
}
