/**
 * 아이콘 한 벌 (선 굵기 1.75, 16칸). 글자 화살표(→ ↗ ▶)와 제각각인 SVG 대신 이것만 쓴다 (2026-11-09).
 * 장식이라 화면 낭독기에는 숨긴다: 뜻은 옆의 글자나 aria-label이 전한다.
 */
const PATHS = {
  refresh: "M13 8a5 5 0 1 1-1.5-3.55M13 2.5v3h-3",
  upload: "M8 10.5V2.5M5 5.5l3-3 3 3M3 10.5v2a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-2",
  sparkle: "M8 2.5l1.3 3.2 3.2 1.3-3.2 1.3L8 11.5 6.7 8.3 3.5 7l3.2-1.3zM12.5 11l.5 1.3 1.3.5-1.3.5-.5 1.2-.5-1.2-1.2-.5 1.2-.5z",
  undo: "M5 6.5H10a3 3 0 0 1 0 6H6.5M7 4 4.5 6.5 7 9",
  download: "M8 2.5v8M5 7.5l3 3 3-3M3 13.5h10",
  copy: "M5.5 5.5V3.5a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-2M3.5 5.5h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-6a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1z",
  play: "M5 3.2v9.6a.6.6 0 0 0 .9.5l7.6-4.8a.6.6 0 0 0 0-1L5.9 2.7a.6.6 0 0 0-.9.5z",
  arrow: "M3 8h10M9 4l4 4-4 4",
  check: "M3.5 8.5l3 3 6-7",
  chevron: "M6 3.5 10.5 8 6 12.5",
  external: "M9.5 2.5h4v4M13.5 2.5 7.5 8.5M11.5 9.5v3a1 1 0 0 1-1 1h-7a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3",
  more: "M3.5 8h.01M8 8h.01M12.5 8h.01",
  close: "M4 4l8 8M12 4l-8 8",
  sun: "M8 10.8a2.8 2.8 0 1 0 0-5.6 2.8 2.8 0 0 0 0 5.6zM8 1.5v1.3M8 13.2v1.3M1.5 8h1.3M13.2 8h1.3M3.4 3.4l.9.9M11.7 11.7l.9.9M3.4 12.6l.9-.9M11.7 4.3l.9-.9",
  moon: "M13.2 9.6A5.5 5.5 0 0 1 6.4 2.8a5.5 5.5 0 1 0 6.8 6.8z",
  monitor: "M2.5 3.5h11a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1zM6 14h4M8 11.5V14",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16, className = "" }: { name: IconName; size?: number; className?: string }) {
  const filled = name === "play";
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill={filled ? "currentColor" : "none"}
      stroke={filled ? "none" : "currentColor"}
      strokeWidth={name === "more" ? 2.6 : 1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`flex-none ${className}`}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
