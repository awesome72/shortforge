"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fileUrl } from "@/lib/api";
import { MOTION_LABEL, TRANSITION_LABEL } from "@/lib/labels";
import type { Timeline } from "@/lib/types";
import { isVideo } from "./Media";
import { Mono } from "./ui";

/** 모션 종류별 시작·끝 transform (FFmpeg zoompan과 같은 방향) */
function motionFrames(type: string, amount: number): Keyframe[] {
  const s = 1 + amount;
  const shift = `${(amount / 2) * 100}%`;
  switch (type) {
    case "zoom_in":
      return [{ transform: "scale(1)" }, { transform: `scale(${s})` }];
    case "zoom_out":
      return [{ transform: `scale(${s})` }, { transform: "scale(1)" }];
    case "pan_left":
      return [{ transform: `scale(${s}) translateX(${shift})` }, { transform: `scale(${s}) translateX(-${shift})` }];
    case "pan_right":
      return [{ transform: `scale(${s}) translateX(-${shift})` }, { transform: `scale(${s}) translateX(${shift})` }];
    default:
      return [{ transform: "scale(1)" }, { transform: "scale(1)" }];
  }
}

// 렌더 자막(app/subtitles.py ASS_STYLES)과 같은 모양: 흰 굵은 글자, 강조만 텅스텐, 훅은 위쪽 큰 제목
const CAPTION_CLS: Record<string, string> = {
  hook_bold: "text-[20px] font-extrabold tracking-[-0.02em] text-white",
  emphasis: "text-[16px] font-bold text-accent",
  body: "text-[15px] font-bold text-white",
};

/**
 * 렌더 전 미리보기 (F-7.4): 장면 이미지·음성·모션·전환·자막을 브라우저에서 이어 재생한다.
 * 렌더 없이 흐름을 확인하는 용도라 BGM과 어절 단위 자막은 빠진다.
 */
export function TimelinePreview({ projectId, timeline, version }: { projectId: string; timeline: Timeline; version: number }) {
  const scenes = timeline.scenes;
  const durations = useMemo(() => scenes.map((s) => (typeof s.duration === "number" ? s.duration : 3)), [scenes]);
  const starts = useMemo(() => durations.map((_, i) => durations.slice(0, i).reduce((a, b) => a + b, 0)), [durations]);
  const total = durations.reduce((a, b) => a + b, 0);

  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const idx = Math.max(0, starts.findLastIndex((s) => s <= t));

  const audios = useRef<HTMLAudioElement[]>([]);
  const bgm = useRef<HTMLAudioElement | null>(null);
  const imgs = useRef<(HTMLImageElement | HTMLVideoElement | null)[]>([]);
  const anim = useRef<Animation | null>(null);
  const clock = useRef({ base: 0, t0: 0 });

  // 음성 파일은 미리 불러 둔다
  useEffect(() => {
    audios.current = scenes.map((s) => {
      const a = new Audio(fileUrl(projectId, s.voice, version) ?? undefined);
      a.preload = "auto";
      return a;
    });
    return () => audios.current.forEach((a) => a.pause());
  }, [scenes, projectId, version]);

  // 배경음악: 렌더와 같은 음량으로 깔되, 덕킹(목소리 구간에서 줄이기)은 렌더에서만 한다
  const bgmUrl = fileUrl(projectId, timeline.audio.bgm, version);
  const bgmGain = timeline.audio.bgm_gain_db;
  useEffect(() => {
    if (!bgmUrl) {
      bgm.current = null;
      return;
    }
    const a = new Audio(bgmUrl);
    a.preload = "auto";
    a.volume = Math.min(1, 10 ** (bgmGain / 20) * 1.6); // 덕킹이 없으니 렌더 체감 음량에 가깝게 조금 올린다
    bgm.current = a;
    return () => a.pause();
  }, [bgmUrl, bgmGain]);
  useEffect(() => {
    const a = bgm.current;
    if (!a) return;
    if (playing) {
      a.currentTime = clock.current.base;
      a.play().catch(() => {});
    } else a.pause();
  }, [playing]);

  // 재생 시계
  useEffect(() => {
    if (!playing) return;
    clock.current = { base: t, t0: performance.now() };
    let raf = 0;
    const tick = () => {
      const now = clock.current.base + (performance.now() - clock.current.t0) / 1000;
      if (now >= total) {
        setT(total);
        setPlaying(false);
        return;
      }
      setT(now);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 시작 시각은 재생을 누른 순간의 t만 쓴다
  }, [playing, total]);

  // 장면이 바뀌거나 재생/정지할 때 음성과 모션을 맞춘다
  useEffect(() => {
    // 재생을 누른 시각이 이 장면 안이면 그 지점부터, 이후 장면은 처음부터
    const offset = Math.max(0, clock.current.base - starts[idx]);
    audios.current.forEach((a, i) => {
      if (i !== idx || !playing) a.pause();
    });
    anim.current?.cancel();
    imgs.current.forEach((el, i) => {
      if (el instanceof HTMLVideoElement && (i !== idx || !playing)) el.pause();
    });
    const img = imgs.current[idx];
    const s = scenes[idx];
    if (img instanceof HTMLVideoElement) {
      // 렌더처럼 장면 시작부터 재생하고, 영상이 짧으면 마지막 프레임에 멈춘다
      img.currentTime = Math.min(playing ? offset : 0, img.duration || 0);
      if (playing) img.play().catch(() => {});
    } else if (img && s) {
      anim.current = img.animate(motionFrames(s.motion.type, s.motion.amount), {
        duration: durations[idx] * 1000,
        fill: "forwards",
        easing: "ease-in-out", // 렌더의 zoompan도 천천히 출발해 천천히 멈춘다
      });
      anim.current.currentTime = playing ? Math.min(offset, durations[idx]) * 1000 : 0;
      if (!playing) anim.current.pause();
    }
    const a = audios.current[idx];
    if (a && playing) {
      a.currentTime = Math.min(offset, a.duration || offset);
      a.play().catch(() => setPlaying(false));
    }
  }, [idx, playing, scenes, starts, durations]);

  const seek = (i: number) => {
    setPlaying(false);
    clock.current.base = starts[i];
    setT(starts[i]);
  };
  const toggle = () => {
    if (t >= total) seek(0);
    else clock.current.base = t;
    setPlaying((p) => !p);
  };

  const cur = scenes[idx];
  return (
    <div className="flex flex-wrap gap-5">
      <div className="flex-none">
        <div className="relative aspect-[9/16] w-[240px] overflow-hidden rounded-xl border border-line-strong bg-sunken">
          {scenes.map((s, i) => {
            const url = fileUrl(projectId, s.image, version);
            const active = i === idx;
            const tr = scenes[i].transition;
            return (
              <div
                key={s.id}
                className="absolute inset-0"
                style={{
                  opacity: active ? 1 : 0,
                  transition: tr.type === "cut" || !active ? "none" : `opacity ${tr.dur}s`,
                }}
              >
                {url &&
                  (isVideo(s.image) ? (
                    <video
                      ref={(el) => {
                        imgs.current[i] = el;
                      }}
                      src={url}
                      muted
                      playsInline
                      preload="auto"
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      ref={(el) => {
                        imgs.current[i] = el;
                      }}
                      src={url}
                      alt=""
                      className="h-full w-full object-cover"
                    />
                  ))}
              </div>
            );
          })}
          {cur && (
            <div
              className={`absolute inset-x-3 text-center leading-snug [text-shadow:0_2px_8px_rgba(0,0,0,.65)] ${cur.caption.style === "hook_bold" ? "top-[16%]" : "bottom-[26%]"}`}
            >
              <span className={CAPTION_CLS[cur.caption.style] ?? CAPTION_CLS.body}>{cur.caption.text}</span>
            </div>
          )}
          <div className="absolute top-2 left-2 rounded bg-black/50 px-1.5 py-0.5 font-mono text-[11px] text-white">
            {cur?.id} · {t.toFixed(1)}/{total.toFixed(1)}s
          </div>
        </div>
        <div className="mt-2 flex h-2 w-[240px] gap-px overflow-hidden rounded-full bg-line">
          {scenes.map((s, i) => (
            <button
              key={s.id}
              type="button"
              aria-label={`${s.id}로 이동`}
              onClick={() => seek(i)}
              className="relative h-full bg-line-strong"
              style={{ flexGrow: durations[i] }}
            >
              <span
                className="absolute inset-y-0 left-0 bg-accent"
                style={{ width: `${Math.min(100, Math.max(0, ((t - starts[i]) / durations[i]) * 100))}%` }}
              />
            </button>
          ))}
        </div>
      </div>
      <div className="flex min-w-0 flex-[1_1_220px] flex-col gap-2 text-[13px]">
        <button
          type="button"
          onClick={toggle}
          className="w-fit rounded-[10px] bg-accent px-4 py-2 text-[13px] font-semibold text-accent-ink hover:bg-accent-strong"
        >
          {playing ? "일시정지" : t > 0 && t < total ? "이어서 재생" : "미리보기 재생"}
        </button>
        <p className="text-muted">
          렌더 없이 장면 그림·음성·움직임·전환을 이어서 봐요. 흐름이 괜찮으면 7단계에서 렌더해 주세요.
        </p>
        <p className="text-[12px] text-muted">
          미리보기는 자막이 장면 단위로 보이고 배경음악이 목소리에 맞춰 작아지지 않아요. 완성 영상은 말에 맞춰 자막을
          나누고, 목소리가 나올 때 음악을 줄여요.
        </p>
        {cur && (
          <div className="mt-1 text-[12px] text-muted">
            지금 장면: <Mono className="text-ink-2">{cur.id}</Mono> · {MOTION_LABEL[cur.motion.type] ?? cur.motion.type}{" "}
            · 전환 {TRANSITION_LABEL[cur.transition.type] ?? cur.transition.type}
          </div>
        )}
      </div>
    </div>
  );
}
