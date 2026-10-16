"""LLM 어댑터 공통: JSON 스키마 강제 + 검증 실패 시 오류를 넣어 재시도 (PROJECT_PROMPT §6, §9).

엔진별 어댑터는 `_complete(system, user, json_schema) -> str`만 구현한다.
이미지 URL을 볼 수 있는 어댑터는 `supports_images = True`로 두고
`_complete(..., images=...)`를 받는다.
"""

from __future__ import annotations

import copy
import re
from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.adapters.base import LLMAdapter, T

MAX_FIX_RETRIES = 2
DROP_KEYS = {"title", "default", "examples"}


class LLMOutputError(RuntimeError):
    pass


@dataclass
class LLMCall:
    task: str
    attempts: int
    ok: bool


@dataclass
class _Log:
    calls: list[LLMCall] = field(default_factory=list)


def llm_schema(model: type) -> dict:
    """Pydantic JSON 스키마의 $ref를 펼치고 LLM이 쓰지 않는 키를 지운다."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                return walk(copy.deepcopy(defs[name]))
            return {k: walk(v) for k, v in node.items() if k not in DROP_KEYS}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


def strip_fences(text: str) -> str:
    """```json ... ``` 같은 코드 펜스를 벗긴다 (소형 로컬 모델이 자주 붙인다)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    return (m.group(1) if m else text).strip()


def _short_errors(e: ValidationError, limit: int = 8) -> str:
    lines = []
    for err in e.errors()[:limit]:
        loc = ".".join(str(x) for x in err["loc"]) or "(root)"
        lines.append(f"- {loc}: {err['msg']}")
    return "\n".join(lines)


class JSONLLMAdapter(LLMAdapter):
    def __init__(self) -> None:
        self.log = _Log()
        self.current_task = ""  # _complete()가 작업별로 모델 등을 고를 때 쓴다
        self.notices: list[str] = []  # 사용자에게 알릴 일 (오케스트레이터가 단계 경고로 옮긴다)

    def drain_notices(self) -> list[str]:
        out, self.notices = self.notices, []
        return out

    @abstractmethod
    async def _complete(self, system: str, user: str, json_schema: dict) -> str: ...

    async def generate_json(
        self, task: str, system: str, user: str, schema: type[T], *, images: Sequence[str] = ()
    ) -> T:
        if images and not self.supports_images:
            raise NotImplementedError(f"{type(self).__name__}는 이미지를 볼 수 없다")
        extra = {"images": list(images)} if images else {}
        json_schema = llm_schema(schema)
        self.current_task = task
        prompt = user
        last: Exception | None = None
        for attempt in range(1, MAX_FIX_RETRIES + 2):
            raw = await self._complete(system, prompt, json_schema, **extra)
            try:
                result = schema.model_validate_json(strip_fences(raw))
            except ValidationError as e:
                last = e
                prompt = (
                    f"{user}\n\n[이전 응답이 스키마 검증에 실패했다. "
                    "아래 오류를 고쳐 JSON만 다시 출력한다]\n"
                    f"{_short_errors(e)}"
                )
                continue
            self.log.calls.append(LLMCall(task, attempt, True))
            return result
        self.log.calls.append(LLMCall(task, MAX_FIX_RETRIES + 1, False))
        raise LLMOutputError(
            f"{task}: LLM 출력이 {MAX_FIX_RETRIES + 1}회 모두 스키마 검증에 실패했다\n{last}"
        )
