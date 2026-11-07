"""이미지 소스 체인 (IMAGE_MODE=cloudflare,stock 등, D12).

설정한 순서대로 시도한다. 한도 초과·오류·결과 없음이면 다음 소스로 넘어가고, 넘어간 이유는
notices에 남긴다(오케스트레이터가 단계 경고로 옮긴다). 모두 실패하면 None → S5가 본인 사진을
돌려 쓰거나 "이미지 없음"으로 남긴다.
"""

from __future__ import annotations

import logging

from app.adapters.base import ImageAdapter, ImageQuotaExceeded, ImageRequest, ImageResult
from app.adapters.run_state import RunNotices, run_state

log = logging.getLogger(__name__)

# 화면에 보일 그림 소스 이름 (설정 값 그대로 보이던 것)
SOURCE_LABEL = {
    "cloudflare": "AI 그림(Cloudflare)",
    "hfspace": "무료 데모 그림",
    "stock": "무료 사진(Pixabay)",
    "pixabay": "무료 사진(Pixabay)",
    "pexels": "무료 사진(Pexels)",
    "video": "무료 동영상",
    "comfyui": "내 GPU 장비",
}


def _label(name: str) -> str:
    return SOURCE_LABEL.get(name, name)


MAX_FAILURES = 2  # 한 실행에서 이만큼 연달아 실패한 소스는 그 실행 동안 건너뛴다


class ImageChain(RunNotices, ImageAdapter):
    def __init__(self, sources: list[tuple[str, ImageAdapter]]) -> None:
        self.sources = sources
        self.wants_english_prompts = any(a.wants_english_prompts for _, a in sources)

    # 아래 둘과 notices는 실행(단계 하나)마다 따로다 (app/adapters/run_state.py)
    @property
    def _exhausted(self) -> set[str]:
        """이번 실행에서 한도가 바닥났거나 계속 실패한 소스. 다시 부르지 않는다."""
        return run_state(self).setdefault("exhausted", set())

    @property
    def _failures(self) -> dict[str, int]:
        """연속 실패 횟수. 한도 문구 없이 계속 실패하는 소스(데모 서버 멈춤)도 장면마다 부르면
        장면당 최대 2분씩 기다리게 된다."""
        return run_state(self).setdefault("failures", {})

    def drain_notices(self) -> list[str]:
        out, self.notices = self.notices, []
        self._exhausted.clear()
        self._failures.clear()
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
            except ImageQuotaExceeded:
                self._exhausted.add(name)
                self._notice(f"{_label(name)} 오늘 한도를 다 써서 다음 그림 소스로 넘겼어요")
                continue
            except Exception as e:  # 한 소스의 장애가 전체를 멈추지 않게 한다
                log.warning("image source %s failed: %s", name, type(e).__name__)
                self._notice(f"{_label(name)}에서 그림을 받지 못해 다음 소스로 넘겼어요")
                self._failures[name] = self._failures.get(name, 0) + 1
                if self._failures[name] >= MAX_FAILURES:
                    self._exhausted.add(name)
                    self._notice(f"{_label(name)} 쪽이 계속 실패해 이번에는 더 쓰지 않았어요")
                continue
            self._failures[name] = 0
            if result is not None:
                return result
        return None
