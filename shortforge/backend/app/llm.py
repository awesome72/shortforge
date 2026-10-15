"""LLM 프롬프트 공통 도구 (PROJECT_PROMPT §9)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str


@cache
def load_prompt(name: str) -> Prompt:
    """app/prompts/{name}.md를 읽는다. 첫 줄은 반드시 'version: x.y'."""
    raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    first, _, body = raw.partition("\n")
    m = re.fullmatch(r"version:\s*(\S+)", first.strip())
    if not m:
        raise ValueError(f"{name}.md 첫 줄에 'version:'이 없다")
    return Prompt(name=name, version=m.group(1), text=body.strip())


def wrap_untrusted(text: str) -> str:
    """외부 텍스트(제목·설명·댓글)를 <untrusted>로 감싼다. 안쪽의 태그 위조를 막는다."""
    cleaned = re.sub(r"</?\s*untrusted\s*>", "", text, flags=re.IGNORECASE)
    return f"<untrusted>{cleaned}</untrusted>"
