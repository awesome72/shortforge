"""단계 실패의 종류. 화면은 문구가 아니라 이 값을 보고 안내와 다음 행동을 고른다.

예외 클래스에 `kind`를 달아 두고 여기서는 찾기만 한다 (어댑터를 import하지 않는다).
값이 늘면 프론트 `lib/failure.ts`도 함께 고친다.

- interrupted: 프로그램이 꺼져 멈춤
- need_photos: 가게 홍보 영상에 사진이 없음
- no_refs: 참고 영상을 찾지 못함 (주제를 바꾸면 해결)
- no_factors: 참고 영상은 있지만 쓸 근거가 없음
- setup: 키가 없거나 틀림
- llm_quota · youtube_quota: 오늘 무료 한도 소진
- llm_busy: AI 서버 과부하·응답 없음
- llm_output: AI 답변이 형식에 맞지 않음
- llm_local: 이 PC의 Ollama가 응답하지 않음
- network: 인터넷 연결 문제
- media · render_stall: FFmpeg 실패·멈춤
- tool_missing: FFmpeg가 없음
- "": 모름 (화면은 일반 안내를 보여 준다)
"""

from __future__ import annotations

import httpx

KINDS = (
    "interrupted", "need_photos", "no_refs", "no_factors", "setup", "llm_quota", "youtube_quota",
    "llm_busy", "llm_output", "llm_local", "network", "media", "render_stall", "tool_missing",
)  # fmt: skip


def failure_kind(error: BaseException) -> str:
    """예외와 그 원인, 묶음(TaskGroup) 안을 차례로 보고 처음 찾은 종류를 돌려준다."""
    stack = [error]
    seen: set[int] = set()
    network = False
    while stack:
        e = stack.pop()
        if id(e) in seen:
            continue
        seen.add(id(e))
        kind = getattr(e, "kind", "")
        if kind and isinstance(kind, str):
            return kind
        if isinstance(e, httpx.TransportError | ConnectionError | TimeoutError):
            network = True
        elif type(e).__module__.startswith("aiohttp"):  # Edge-TTS
            network = True
        if isinstance(e, BaseExceptionGroup):
            stack.extend(e.exceptions)
        if e.__cause__ is not None:
            stack.append(e.__cause__)
    return "network" if network else ""
