import { useSyncExternalStore } from "react";

const QUERY = "(max-width: 1279.98px)"; // Tailwind xl 아래: 인스펙터가 본문 아래로 내려가는 폭

/** 좁은 화면인지 (서버 렌더에서는 넓은 화면으로 본다) */
export function useNarrow(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(QUERY);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(QUERY).matches,
    () => false,
  );
}
