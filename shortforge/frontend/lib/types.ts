// backend/app/schemas/project.py 와 같은 모양. 계약이 바뀌면 함께 바꾼다.

export const STEP_IDS = ["s1", "s2", "s3", "s4", "s5", "s6", "s7"] as const;
export type StepId = (typeof STEP_IDS)[number];
export type StepState = "idle" | "running" | "done" | "stale" | "error";
export type OutputKey = "input" | "refs" | "factors" | "strategy" | "assets" | "timeline" | "render";

export interface Input {
  topic: string;
  audience: string;
  tone: "empathetic" | "informative" | "humor";
  duration_sec: 15 | 30 | 60;
  aspect: "9:16";
  lang: string;
  region: string;
  user_media: string[];
  keywords: string[];
}

export interface Ref {
  video_id: string;
  title: string;
  channel_id: string;
  subs: number | null;
  views: number;
  likes: number;
  comments: number;
  duration_sec: number;
  published_at: string;
  ratio_views_per_sub: number | null;
  views_per_day: number;
  like_rate: number;
  score: number;
  thumbnail_url: string;
  relevant: boolean | null;
  selected: boolean;
  fetched_at: string;
}

export type FactorName = "hook" | "title" | "length" | "empathy" | "visual" | "timing" | "cta";

export interface Factor {
  name: FactorName;
  finding: string;
  evidence: string[];
  confidence: "confirmed" | "estimated";
}

export interface Scene {
  id: string;
  role: "hook" | "problem" | "method" | "payoff" | "cta";
  start: number;
  end: number;
  line: string;
  visual: string;
  factor_refs: FactorName[];
}

export interface Strategy {
  titles: string[];
  post_time_hint: string;
  differentiator: string;
  style_seed: string;
  scenes: Scene[];
}

export interface Asset {
  scene_id: string;
  image: {
    prompt: string;
    negative: string;
    seed: number;
    source: "generated" | "user" | "stock";
    path: string | null;
    query: string;
    provider: string | null;
    credit: string | null;
  };
  voice: {
    text: string;
    voice: string;
    rate: string;
    path: string | null;
    duration_sec: number | null;
    words_path: string | null;
  };
}

export interface TimelineScene {
  id: string;
  image: string;
  voice: string;
  duration: number | "auto";
  pad: number;
  motion: { type: string; amount: number };
  transition: { type: string; dur: number };
  caption: { text: string; style: string };
  gen_video: boolean;
}

export interface Timeline {
  canvas: { w: number; h: number; fps: number };
  audio: { bgm: string | null; bgm_gain_db: number; duck_db: number };
  scenes: TimelineScene[];
  subtitles: { source: string; burn_in: boolean; max_chars_per_line: number };
}

export interface Render {
  path: string;
  srt: string;
  duration_sec: number;
  log: string;
}

export interface Project {
  id: string;
  version: number;
  parent_id: string | null; // A/B 변형이면 원본 ID
  variant: string | null; // "B", "C" …
  updated_at: string;
  status: Record<StepId, StepState>;
  errors: Partial<Record<StepId, string>>;
  warnings: Partial<Record<StepId, string[]>>;
  input: Input | null;
  refs: Ref[] | null;
  factors: Factor[] | null;
  strategy: Strategy | null;
  assets: Asset[] | null;
  timeline: Timeline | null;
  render: Render | null;
  // GET /projects/{id} 부가 정보
  busy: boolean;
  blockers: Record<StepId, StepId[]>;
}

export interface ProjectRow {
  id: string;
  topic: string;
  version: number;
  updated_at: string;
  parent_id: string | null;
  variant: string | null;
}

export interface VersionSummary {
  version: number;
  updated_at: string;
  status: Record<StepId, StepState>;
  title: string | null;
  has_render: boolean;
}

export interface Quota {
  day_pt: string;
  used: number;
  search_limit: number;
  hard_limit: number;
  search_blocked: boolean;
  images?: { day_utc: string; used: number; limit: number }; // Cloudflare Neurons
}

export interface AppConfig {
  llm_mode: "gemini" | "ollama" | "fake";
  llm_model: string | null;
  image_mode: string;
  image_sources: string[];
  tts_mode: string;
  tts_voice: string;
  render_preset: string;
  free_tier_notice: boolean;
}

export type PipelineEvent =
  | { type: "step_started"; step: StepId }
  | { type: "step_progress"; step: StepId; stage: string; progress: number }
  | { type: "step_done"; step: StepId; version: number }
  | { type: "step_error"; step: StepId; error: string }
  | { type: "run_finished"; version: number }
  | { type: "run_failed"; error: string }
  | { type: "edited"; key: OutputKey; version: number };
