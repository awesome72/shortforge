import type { Input } from "./types";

/** '검색어 새로 만들기': 지금 검색어를 비우고 '결과가 없던 검색어'로 넘긴다.
 *  같은 검색어로 다시 시도하면 캐시된 빈 결과가 나온다(13번 연달아 실패한 일). 쉬운·전문가 화면이 함께 쓴다. */
export function freshKeywords(input: Input): Input {
  const tried = [...(input.keywords_failed ?? []), ...input.keywords];
  return {
    ...input,
    keywords: [],
    keywords_auto: [],
    world_keywords: [],
    keywords_failed: [...new Set(tried)].slice(-10), // 다시 만들 때 피한다
  };
}
