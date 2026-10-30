import type { FactorName, StepId, StepState } from "./types";

export const STEPS: Record<StepId, { n: number; label: string; sub: string }> = {
  s1: { n: 1, label: "개인 입력", sub: "주제 · 타깃 · 톤" },
  s2: { n: 2, label: "레퍼런스 탐색", sub: "구독자 대비 상위 숏폼" },
  s3: { n: 3, label: "성공 요인 분석", sub: "근거와 신뢰도" },
  s4: { n: 4, label: "제작 전략", sub: "장면 스토리보드" },
  s5: { n: 5, label: "자산 생성", sub: "장면별 이미지 · 음성" },
  s6: { n: 6, label: "편집 지시서", sub: "장면 길이 · 모션 · 전환" },
  s7: { n: 7, label: "렌더", sub: "MP4 · SRT 1080×1920" },
};

export const STATE_LABEL: Record<StepState, string> = {
  idle: "대기",
  running: "실행 중",
  done: "완료",
  stale: "재생성 필요",
  error: "오류",
};

export const FACTOR_LABEL: Record<FactorName, string> = {
  hook: "훅 (0–2초)",
  title: "제목 구조",
  length: "길이",
  empathy: "공감 장치",
  visual: "화면 구성",
  timing: "게시 시각",
  cta: "행동 유도",
};

export const ROLE_LABEL: Record<string, string> = {
  hook: "훅",
  problem: "문제",
  method: "방법",
  payoff: "결과",
  cta: "행동 유도",
};

/** 장면 역할 색 (globals.css의 --color-role-*). 스토리보드 막대·역할 표시에 쓴다 */
export const ROLE_COLOR: Record<string, string> = {
  hook: "var(--color-role-hook)",
  problem: "var(--color-role-problem)",
  method: "var(--color-role-method)",
  payoff: "var(--color-role-payoff)",
  cta: "var(--color-role-cta)",
};

/** S3 근거 필드 (YouTube API 이름) → 화면 이름 */
export const EVIDENCE_LABEL: Record<string, string> = {
  "snippet.title": "제목",
  "snippet.publishedAt": "게시 시각",
  "contentDetails.duration": "길이",
  "statistics.viewCount": "조회수",
  "statistics.likeCount": "좋아요",
  "channel.subscriberCount": "구독자",
  commentThreads: "댓글",
  thumbnail: "썸네일",
};

export const MOTION_LABEL: Record<string, string> = {
  zoom_in: "천천히 확대",
  zoom_out: "천천히 축소",
  pan_left: "왼쪽으로 이동",
  pan_right: "오른쪽으로 이동",
  static: "고정",
};

// 슬라이드는 렌더에서 크로스페이드로 바꿔 쓴다 (예전 지시서 표시용)
export const TRANSITION_LABEL: Record<string, string> = { cut: "컷", fade: "페이드", slide: "페이드" };

/** 1단계 그림체 (백엔드 image_prompt.VISUAL_STYLES와 같은 키) */
export const VISUAL_STYLE_LABEL = {
  auto: "자동",
  photo: "사진",
  cinematic: "시네마틱",
  illustration: "일러스트",
  watercolor: "수채화",
} as const;

export const CAPTION_LABEL: Record<string, string> = { hook_bold: "훅 강조", emphasis: "강조", body: "기본" };

/** 배경음악 분위기 (백엔드 app/music.py MOOD_LABEL과 같은 목록) */
export const MOOD_LABEL: Record<string, string> = {
  calm: "잔잔한",
  warm: "따뜻한",
  upbeat: "경쾌한",
  inspiring: "벅차오르는",
  focus: "차분한 정보",
  playful: "유쾌한",
  tense: "긴장감 있는",
};

export const VOICE_LABEL = { auto: "자동", female: "여성", male: "남성" } as const;

export const TONE_LABEL = { empathetic: "공감 · 담백", informative: "정보 · 단호", humor: "유머" } as const;

// PRD §8 무료 스택과 한도
export const FREE_TOOLS: Record<StepId, { name: string; limit: string; risk: string }[]> = {
  s1: [{ name: "Gemini Flash 무료 / Ollama", limit: "분당·일일 호출 제한", risk: "무료 등급은 상업 이용 제외" }],
  s2: [
    { name: "YouTube Data API v3", limit: "10,000 units/일 · 검색 100 units", risk: "쿼터 증설은 심사 필요" },
    { name: "Gemini (관련성 판정)", limit: "호출 1회", risk: "실패해도 점수 순으로 진행" },
  ],
  s3: [
    { name: "Gemini Flash 무료 / Ollama", limit: "댓글 조회 1 unit/영상", risk: "시청 지속률은 API가 주지 않음 → 추정" },
  ],
  s4: [{ name: "Gemini Flash 무료 / Ollama", limit: "최대 3회 재생성", risk: "레퍼런스 제목 복사 금지 (Jaccard ≤ 0.6)" }],
  s5: [
    { name: "Edge-TTS (ko-KR)", limit: "무료 · 비공식 엔드포인트", risk: "상업 이용 시 MeloTTS로 전환" },
    {
      name: "Cloudflare Workers AI · FLUX.2 klein",
      limit: "하루 10,000 Neurons ≈ 64장 (00:00 UTC 초기화)",
      risk: "BFL 약관 확인 후 상업 이용",
    },
    { name: "Pixabay 무료 사진", limit: "60초당 100회 · 검색 24시간 캐시", risk: "인물 사진은 초상권 주의" },
  ],
  s6: [{ name: "규칙 기반 + LLM 연출", limit: "LLM 실패 시 규칙 기반", risk: "경로·길이는 항상 규칙으로 결정" }],
  s7: [
    { name: "FFmpeg (libx264 veryfast)", limit: "CPU로 30초 영상 약 50초", risk: "—" },
    { name: "TTS 어절 타이밍 자막", limit: "Whisper 불필요", risk: "사용자 녹음 음성은 Whisper 사용" },
  ],
};

export function fmtNum(n: number): string {
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}

// 해외 레퍼런스 시장 이름 (없는 코드는 그대로 보여 준다)
export const MARKET_LABEL: Record<string, string> = { US: "미국", JP: "일본", GB: "영국", IN: "인도", BR: "브라질", MX: "멕시코", ES: "스페인", FR: "프랑스", DE: "독일", };
