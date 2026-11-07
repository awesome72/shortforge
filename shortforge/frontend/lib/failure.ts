// 단계 실패 안내. 종류는 백엔드 app/failure.py와 같다. 값이 늘면 함께 고친다
export type FailureAction = "settings" | "topic" | "photos" | "keywords";

type Failure = { text: string; action?: FailureAction };

const FAILURES: Record<string, Failure> = {
  interrupted: { text: "프로그램이 꺼져 멈췄어요. 다시 시도하면 이어서 해요." },
  cancelled: { text: "멈췄어요. 이전 결과는 그대로예요." },
  need_photos: {
    text: "홍보 영상은 실제 사진이 필요해요.",
    action: "photos",
  },
  no_refs: {
    text: "주제에 맞는 참고 영상을 찾지 못했어요. 검색어를 바꾸거나 주제를 넓혀 보세요.",
    action: "keywords",
  },
  no_factors: {
    text: "참고 영상에서 쓸 내용을 찾지 못했어요. 주제를 조금 바꿔 보세요.",
    action: "topic",
  },
  setup: { text: "키가 없거나 맞지 않아요. 설정에서 확인해 주세요.", action: "settings" },
  // 두 한도 모두 태평양 시간 자정(한국 오후 4시, 겨울에는 5시)에 다시 채워진다. '내일'이 아니다
  llm_quota: {
    text: "오늘 AI 무료 한도를 다 썼어요. 오후 4시(겨울 5시)에 다시 채워져요.",
  },
  youtube_quota: {
    text: "오늘 YouTube 검색 한도를 다 썼어요. 오후 4시(겨울 5시)에 다시 채워져요.",
  },
  llm_busy: { text: "AI 서버가 지금 붐벼요. 몇 분 뒤 다시 시도해 주세요." },
  llm_output: { text: "AI 답변이 잘못 왔어요. 다시 시도해 보세요." },
  llm_local: { text: "이 PC의 AI 프로그램(Ollama)이 응답하지 않아요. 켜져 있는지 확인해 주세요." },
  network: { text: "인터넷 연결이 불안정해요. 확인하고 다시 시도해 주세요." },
  render_stall: { text: "영상을 합치다가 멈췄어요. 지난 영상은 그대로예요." },
  media: { text: "영상·소리를 처리하다 멈췄어요. 다시 시도해 보세요." },
  tool_missing: { text: "영상 프로그램(FFmpeg)을 찾지 못했어요. setup.bat을 다시 실행해 주세요." },
};

/** 종류를 모르면 null. 화면은 일반 안내를 보여 준다 */
export function failureOf(kind: string | undefined): Failure | null {
  return (kind && FAILURES[kind]) || null;
}
