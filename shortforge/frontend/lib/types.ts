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
  visual_style: "auto" | "photo" | "cinematic" | "illustration" | "watercolor";
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
    basis?: string | null; // 이미지를 정한 장면 묘사+스타일 시드 (S5 재실행 때 재사용)
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
  audio: AudioMix;
  scenes: TimelineScene[];
  subtitles: { source: string; burn_in: boolean; max_chars_per_line: number };
}

export interface AudioMix {
  bgm: string | null;
  bgm_gain_db: number;
  duck_db: number;
  source: "generated" | "user" | null; // 합성한 곡 | 직접 올린 음악 | 없음
  mood: string | null; // labels.ts MOOD_LABEL의 키
  variant: number;
  locked: boolean; // 사용자가 고름 (6단계를 다시 실행해도 유지)
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
  llm_usage?: Partial<Record<StepId, StepLLMUsage>>; // 이 단계를 처리한 모델과 고급 모드 비용
  // GET /projects/{id} 부가 정보
  busy: boolean;
  blockers: Record<StepId, StepId[]>;
  not_ready?: Partial<Record<StepId, string>>; // 앞 단계는 끝났지만 내용이 모자라 실행해도 실패할 이유
}

export interface StepLLMUsage {
  models: string[];
  providers: string[]; // gemini | anthropic | openai | openrouter
  calls: number;
  usd: number;
}

export interface ProjectRow {
  id: string;
  topic: string;
  version: number;
  updated_at: string;
  parent_id: string | null;
  variant: string | null;
  stages: string; // 단계 상태를 쉼표로 이은 것 ("done,done,idle,…")
  thumb: string | null; // 첫 장면 이미지 (프로젝트 폴더 기준 경로)
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
  setup_problems?: string[]; // .env에 빠진 키 (서버는 떠 있고 해당 단계만 실패)
  advanced?: AdvancedInfo | null; // 고급 모드(유료)가 실제로 켜져 있을 때만
  image_unused?: string[]; // 키는 있는데 이미지 방식에 들어 있지 않은 소스
}

/** 고급 모드(D13): 지정한 작업만 사용자 키로 유료 모델을 쓴다 */
export interface AdvancedInfo {
  provider: string;
  model: string;
  label: string;
  tasks: string[];
  day_utc: string;
  used_usd: number;
  budget_usd: number;
}

export type AdvancedProvider = "anthropic" | "openai" | "openrouter";

export interface AdvancedStatus {
  mode: "off" | AdvancedProvider;
  provider: AdvancedProvider;
  providers: Record<AdvancedProvider, string>;
  defaults: Record<AdvancedProvider, string>; // 서비스별 추천 모델
  model: string;
  effort: "low" | "medium" | "high";
  tasks: string[];
  budget_usd: number;
  models: Record<string, Record<string, { label: string; input: number; output: number }>>;
  spend: { day_utc: string; used_usd: number; budget_usd: number };
}

export interface KeyField {
  name: string; // .env 이름 (YOUTUBE_API_KEY 등)
  label: string;
  hint: string;
  url: string;
  set: boolean; // 값은 서버가 내보내지 않는다
  group: "basic" | "advanced";
}

export interface KeyStatus {
  fields: KeyField[];
  image_mode: string;
  image_modes: Record<string, string>;
  llm_mode: string;
  advanced: AdvancedStatus;
}

/** ok: null = 응답을 받지 못함(네트워크·한도). 저장은 허용된다 */
export type KeyCheck = Record<string, { ok: boolean | null; message: string }>;

export type PipelineEvent =
  | { type: "step_started"; step: StepId }
  | { type: "step_progress"; step: StepId; stage: string; progress: number }
  | { type: "step_done"; step: StepId; version: number }
  | { type: "step_error"; step: StepId; error: string }
  | { type: "run_finished"; version: number }
  | { type: "run_failed"; error: string }
  | { type: "edited"; key: OutputKey; version: number };

export type ImageAsset = Asset["image"];

export interface PublishKit {
  checklist: { id: string; text: string; auto: boolean }[];
  description: string;
  voices: string[];
  counts: { generated: number; stock: number; user: number };
}
