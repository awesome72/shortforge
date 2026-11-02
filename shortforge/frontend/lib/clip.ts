import type { Project, VideoGenStatus } from "./types";

const CLIP_SEC = [1.5, 8]; // 서버의 영상 길이 범위 (adapters/video_gen/hf.py)

/** 유료 방식의 장면 영상 값(달러, 위로 올림). 서버의 frames_for와 같은 방식으로 어림한다 */
export function clipPrice(project: Project, videoGen: VideoGenStatus | null | undefined, sceneId: string): number {
  const planned = project.timeline?.scenes.find((s) => s.id === sceneId)?.duration;
  const voice = (project.assets ?? []).find((a) => a.scene_id === sceneId)?.voice;
  const sec = (typeof planned === "number" ? planned : (voice?.speech_sec ?? voice?.duration_sec ?? 3)) + 0.5;
  const clamped = Math.min(Math.max(sec, CLIP_SEC[0]), CLIP_SEC[1]);
  const frames = Math.ceil((clamped * (videoGen?.fps ?? 25)) / 8) * 8 + 1;
  return Math.ceil(frames * (videoGen?.usd_per_frame ?? 0) * 100) / 100;
}
