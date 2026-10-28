"use client";

import { useRef, useState, type PointerEvent, type ReactEventHandler } from "react";

/** 장면 소스가 동영상인지 (백엔드 app/media.VIDEO_EXT와 같은 확장자) */
export const isVideo = (path?: string | null) => !!path && /\.(mp4|mov|m4v|webm)$/i.test(path);

/**
 * 장면 소스 한 장: 사진은 img, 동영상은 소리 없이 반복 재생한다.
 * play가 거짓이면 첫 프레임만 보여 준다 (목록에서 여러 영상을 한꺼번에 재생하지 않게).
 */
export function SceneMedia({
  src,
  path,
  className = "",
  play = false,
}: {
  src: string;
  path?: string | null;
  className?: string;
  play?: boolean;
}) {
  if (isVideo(path ?? src))
    return (
      <video
        key={`${src}-${play}`}
        src={`${src}#t=0.1`}
        muted
        playsInline
        loop
        autoPlay={play}
        preload="metadata"
        className={className}
      />
    );
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt="" loading="lazy" className={className} />;
}

// 브라우저 기본 재생기는 밝은 회색 막대라 어두운 편집실 화면에서 떠 보인다. 같은 토큰으로 직접 그린다

const fmt = (sec: number) => {
  const s = Math.max(0, Math.floor(sec || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

function PlayPause({ playing }: { playing: boolean }) {
  return playing ? (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true">
      <rect x="3.5" y="2.5" width="3" height="11" rx=".8" />
      <rect x="9.5" y="2.5" width="3" height="11" rx=".8" />
    </svg>
  ) : (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true">
      <path d="M4.5 2.8v10.4a.6.6 0 0 0 .9.5l8.3-5.2a.6.6 0 0 0 0-1L5.4 2.3a.6.6 0 0 0-.9.5z" />
    </svg>
  );
}

/** 재생 위치 막대: 누르거나 끌어서 옮기고, 방향키로도 옮긴다 */
function Scrubber({
  t,
  total,
  onSeek,
  label,
  className = "",
}: {
  t: number;
  total: number;
  onSeek: (t: number) => void;
  label: string;
  className?: string;
}) {
  const pct = total > 0 ? Math.min(100, (t / total) * 100) : 0;
  const seekAt = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    onSeek(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * total);
  };
  return (
    <div
      role="slider"
      tabIndex={0}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={Math.round(total)}
      aria-valuenow={Math.round(t)}
      aria-valuetext={`${fmt(t)} / ${fmt(total)}`}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        seekAt(e);
      }}
      onPointerMove={(e) => e.buttons === 1 && seekAt(e)}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight") onSeek(Math.min(total, t + 1));
        else if (e.key === "ArrowLeft") onSeek(Math.max(0, t - 1));
        else return;
        e.preventDefault();
      }}
      className={`group relative flex h-4 cursor-pointer items-center outline-none ${className}`}
    >
      <span className="h-[3px] w-full overflow-hidden rounded-full bg-white/15">
        <span className="block h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </span>
      <span
        className="absolute size-2.5 -translate-x-1/2 rounded-full bg-accent opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
        style={{ left: `${pct}%` }}
      />
    </div>
  );
}

function useMedia<T extends HTMLMediaElement>() {
  const ref = useRef<T>(null);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);
  const [total, setTotal] = useState(0);
  const events: Record<string, ReactEventHandler<T>> = {
    onPlay: () => setPlaying(true),
    onPause: () => setPlaying(false),
    onEnded: () => setPlaying(false),
    onTimeUpdate: (e) => setT(e.currentTarget.currentTime),
    onLoadedMetadata: (e) => setTotal(e.currentTarget.duration),
    onDurationChange: (e) => setTotal(e.currentTarget.duration),
  };
  const toggle = () => {
    const m = ref.current;
    if (!m) return;
    if (m.paused) m.play().catch(() => setPlaying(false));
    else m.pause();
  };
  const seek = (to: number) => {
    if (ref.current) ref.current.currentTime = to;
    setT(to);
  };
  return { ref, playing, t, total, events, toggle, seek };
}

/** 장면 음성 재생기 (한 줄) */
export function AudioPlayer({ src, label = "음성" }: { src: string; label?: string }) {
  const { ref, ...m } = useMedia<HTMLAudioElement>();
  return (
    <div className="flex h-9 w-full max-w-[300px] items-center gap-2.5 rounded-full border border-line-strong bg-sunken pr-3.5 pl-1">
      <audio ref={ref} src={src} preload="metadata" {...m.events} />
      <button
        type="button"
        onClick={m.toggle}
        aria-label={m.playing ? `${label} 일시정지` : `${label} 재생`}
        className="flex size-7 flex-none items-center justify-center rounded-full bg-card text-ink transition-colors hover:bg-accent hover:text-accent-ink"
      >
        <PlayPause playing={m.playing} />
      </button>
      <Scrubber t={m.t} total={m.total} onSeek={m.seek} label={`${label} 재생 위치`} className="flex-1" />
      <span className="flex-none text-[11.5px] tabular-nums text-muted">
        {fmt(m.t)} / {fmt(m.total)}
      </span>
    </div>
  );
}

/** 완성 영상 재생기: 화면을 누르면 재생·정지, 아래 막대로 이동, 전체 화면 */
export function VideoPlayer({
  src,
  className = "",
  style,
}: {
  src: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  const { ref, ...m } = useMedia<HTMLVideoElement>();
  const [muted, setMuted] = useState(false);
  const icon = "flex size-7 flex-none items-center justify-center rounded-full text-white/85 hover:bg-white/15";
  return (
    <div className={`group relative overflow-hidden bg-black ${className}`} style={style}>
      <video
        ref={ref}
        src={src}
        playsInline
        preload="metadata"
        muted={muted}
        onClick={m.toggle}
        className="h-full w-full cursor-pointer object-contain"
        {...m.events}
      />
      {!m.playing && (
        <button
          type="button"
          onClick={m.toggle}
          aria-label="재생"
          className="absolute inset-0 m-auto flex size-12 items-center justify-center rounded-full bg-black/55 text-white backdrop-blur-sm transition-colors hover:bg-accent hover:text-accent-ink"
        >
          <svg viewBox="0 0 16 16" width="18" height="18" fill="currentColor" aria-hidden="true">
            <path d="M4.5 2.8v10.4a.6.6 0 0 0 .9.5l8.3-5.2a.6.6 0 0 0 0-1L5.4 2.3a.6.6 0 0 0-.9.5z" />
          </svg>
        </button>
      )}
      <div
        className={`absolute inset-x-0 bottom-0 flex items-center gap-1.5 bg-[linear-gradient(transparent,rgba(0,0,0,.75))] px-2 pt-6 pb-1.5 transition-opacity ${m.playing ? "opacity-0 group-focus-within:opacity-100 group-hover:opacity-100" : "opacity-100"}`}
      >
        <button type="button" onClick={m.toggle} className={icon} aria-label={m.playing ? "일시정지" : "재생"}>
          <PlayPause playing={m.playing} />
        </button>
        <Scrubber t={m.t} total={m.total} onSeek={m.seek} label="재생 위치" className="flex-1" />
        <span className="flex-none px-1 text-[11px] tabular-nums text-white/80">
          {fmt(m.t)} / {fmt(m.total)}
        </span>
        <button
          type="button"
          onClick={() => setMuted((x) => !x)}
          className={icon}
          aria-label={muted ? "소리 켜기" : "소리 끄기"}
        >
          <svg
            viewBox="0 0 16 16"
            width="13"
            height="13"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            aria-hidden="true"
          >
            <path d="M2.5 6v4h2.5l3.5 3V3L5 6z" fill="currentColor" stroke="none" />
            {muted ? (
              <path d="M11 6l3.5 4M14.5 6L11 10" strokeLinecap="round" />
            ) : (
              <path d="M11 5.5a3.5 3.5 0 0 1 0 5M12.8 3.8a6 6 0 0 1 0 8.4" strokeLinecap="round" />
            )}
          </svg>
        </button>
        <button
          type="button"
          onClick={() => ref.current?.parentElement?.requestFullscreen?.().catch(() => {})}
          className={icon}
          aria-label="전체 화면"
        >
          <svg
            viewBox="0 0 16 16"
            width="13"
            height="13"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10" />
          </svg>
        </button>
      </div>
    </div>
  );
}
