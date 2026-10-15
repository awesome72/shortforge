"""이미지 소스 체인 (IMAGE_MODE=cloudflare,stock 등, D12).

설정한 순서대로 시도한다. 한도 초과·오류·결과 없음이면 다음 소스로 넘어가고, 넘어간 이유는
notices에 남긴다(오케스트레이터가 단계 경고로 옮긴다). 모두 실패하면 None → S5가 본인 사진을
돌려 쓰거나 "이미지 없음"으로 남긴다.
"""

from __future__ import annotations

from app.adapters.base import ImageAdapter, ImageQuotaExceeded, ImageRequest, ImageResult


class ImageChain(ImageAdapter):
    def __init__(self, sources: list[tuple[str, ImageAdapter]]) -> None:
        self.sources = sources
        self.wants_english_prompts = any(a.wants_english_prompts for _, a in sources)
        self.notices: list[str] = []
        self._exhausted: set[str] = set()  # 이번 실행에서 한도가 바닥난 소스는 다시 부르지 않는다

    def drain_notices(self) -> list[str]:
        out, self.notices = self.notices, []
        self._exhausted.clear()
        return out

    def _notice(self, msg: str) -> None:
        if msg not in self.notices:
            self.notices.append(msg)

    async def generate(self, req: ImageRequest) -> ImageResult | None:
        for name, adapter in self.sources:
            if name in self._exhausted:
                continue
            try:
                result = await adapter.generate(req)
            except ImageQuotaExceeded as e:
                self._exhausted.add(name)
                self._notice(f"{name}: {e} — 다음 이미지 소스로 넘겼다")
                continue
            except Exception as e:  # 한 소스의 장애가 전체를 멈추지 않게 한다
                reason = f"{type(e).__name__}: {str(e)[:120]}"
                self._notice(f"{name} 실패({reason}) — 다음 소스로 넘겼다")
                continue
            if result is not None:
                return result
        return None
