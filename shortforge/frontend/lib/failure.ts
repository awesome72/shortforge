// 단계 실패 안내. 종류는 백엔드 app/failure.py와 같다. 값이 늘면 함께 고친다
export type FailureAction = "settings" | "topic" | "photos" | "keywords";

type Failure = { text: string; action?: FailureAction };

const FAILURES: Record<string, Failure> = {
  interrupted: { text: "프로그램이 꺼져 멈췄어요. 다시 시도를 누르면 이어서 만들어요." },
  cancelled: { text: "멈췄어요. 이전 결과는 그대로예요. 다시 시도를 누르면 이 단계부터 이어서 만들어요." },
  need_photos: {
    text: "가게 홍보 영상은 실제 사진이 필요해요. 사진을 올리면 이어서 만들어요.",
    action: "photos",
  },
  no_refs: {
    text: "주제에 맞는 참고 영상을 찾지 못했어요. 검색어를 새로 만들어 다시 찾아볼 수 있어요. 주제를 넓게 바꿔도 좋아요.",
    action: "keywords",
  },
  no_factors: {
    text: "참고 영상에서 쓸 만한 내용을 찾지 못했어요. 다시 시도하거나 주제를 조금 바꿔 보세요.",
    action: "topic",
  },
  setup: { text: "서비스 키가 없거나 맞지 않아요. 설정에서 키를 확인해 주세요.", action: "settings" },
  llm_quota: { text: "오늘 쓸 수 있는 AI 무료 한도를 다 썼어요. 내일 다시 시도해 주세요." },
  youtube_quota: { text: "오늘 쓸 수 있는 YouTube 검색 한도를 다 썼어요. 내일 다시 시도해 주세요." },
  llm_busy: { text: "AI 서버가 지금 붐벼요. 몇 분 뒤 다시 시도해 주세요." },
  llm_output: { text: "AI 답변이 형식에 맞지 않았어요. 다시 시도하면 대부분 해결돼요." },
  llm_local: { text: "이 PC의 AI 프로그램(Ollama)이 응답하지 않아요. 켜져 있는지 확인해 주세요." },
  network: { text: "인터넷 연결이 불안정해요. 연결을 확인하고 다시 시도해 주세요." },
  render_stall: { text: "영상을 합치다가 멈췄어요. 다시 시도해 주세요. 지난 영상은 그대로 있어요." },
  media: { text: "영상이나 소리를 처리하다가 문제가 생겼어요. 다시 시도해 주세요." },
  tool_missing: { text: "영상 프로그램(FFmpeg)을 찾지 못했어요. setup.bat을 다시 실행해 주세요." },
};

/** 종류를 모르면 null. 화면은 일반 안내를 보여 준다 */
export function failureOf(kind: string | undefined): Failure | null {
  return (kind && FAILURES[kind]) || null;
}
