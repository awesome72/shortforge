import type { Scene } from "./types";

/** S4 review()의 HOOK_MAX_END와 같다: 첫 장면은 0~2초 hook이어야 한다 */
export const HOOK_MAX_END = 2;

const round1 = (x: number) => Math.round(x * 10) / 10;

/** 장면 i를 j 자리로 옮긴다. 장면마다 길이는 그대로 두고 시작·끝 시각을 순서대로 다시 계산한다. */
export function moveScene(scenes: Scene[], i: number, j: number): Scene[] {
  if (i === j || j < 0 || j >= scenes.length) return scenes;
  const next = [...scenes];
  const [moved] = next.splice(i, 1);
  next.splice(j, 0, moved);
  let t = 0;
  return next.map((s) => {
    const start = round1(t);
    t += s.end - s.start;
    return { ...s, start, end: round1(t) };
  });
}

/** 저장할 때 장면 ID를 순서대로 S1…Sn으로 다시 붙인다 (5단계 자산·자막이 이 순서를 따른다). */
export function renumber(scenes: Scene[]): Scene[] {
  return scenes.map((s, k) => ({ ...s, id: `S${k + 1}` }));
}

/** 순서를 바꾼 결과가 S4 검사(첫 장면 = 0~2초 hook)를 깨면 안내 문구를 돌려준다. */
export function hookWarning(scenes: Scene[]): string | null {
  const first = scenes[0];
  if (!first) return null;
  if (first.role !== "hook") return "첫 장면이 훅이 아니다. 숏폼은 첫 2초에 이탈이 가장 많으니 훅 장면을 맨 앞에 두기를 권한다.";
  if (first.end > HOOK_MAX_END) return `첫 장면이 ${first.end}초로 길다. 훅은 ${HOOK_MAX_END}초 이내를 권한다.`;
  return null;
}
