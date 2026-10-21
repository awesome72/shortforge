"""이미지 생성 프롬프트 다듬기 (S5·장면 이미지 다시 만들기·후보 공통).

실측(2026-10-21): S4의 style_seed("…, 굵은 흰색 자막, 세로 9:16 숏폼 스타일")를 그대로 붙였더니
FLUX가 장면마다 큰 영문 문구("Start Writing Your Story.", "Agreement in Progress")를 그려 넣었다.
style_seed는 영상(자막·레이아웃) 스타일이지 그림 묘사가 아니다. 또 FLUX에는 negative 입력이 없고,
"no face shown"·"no text" 같은 부정문은 오히려 그 대상을 그리게 만든다.

그래서
- 글자를 부르는 말(자막·제목·로고·포스터·간판, 따옴표 속 문구)과 화면비·레이아웃 말(9:16, 숏폼),
  부정문 조각을 프롬프트에서 뺀다. 마지막 요청 직전에도 한 번 더 거른다
  (예전 프로젝트의 다시 만들기 대비).
- 사진 품질을 정하는 공통 문구(빛·렌즈·심도)를 붙인다.
"""

from __future__ import annotations

import re

# 생성 이미지 프롬프트 규칙이 바뀌면 올린다.
# 이보다 낮은 생성 이미지는 S5를 다시 실행할 때 새로 만든다
# 2: 자막·화면비·부정문 제거, 864×1536 / 3: 주인공 고정(subject)·지역에 맞는 인물·얼굴 장면 줄이기
PROMPT_REV = 3

QUALITY = (
    "candid documentary photograph, natural light, shallow depth of field, 35mm lens, fine detail"
)

_TEXT_TERMS = re.compile(
    r"자막|글자|글씨|텍스트|문구|타이포|제목|로고|캡션|워터마크|간판|슬로건|해시태그|현수막|포스터|"
    r"9\s*:\s*16|화면비|세로\s*화면|숏폼|쇼츠|썸네일|레이아웃|"
    r"\b(?:text|texts|caption|captions|subtitle|subtitles|typography|title|titles|logo|logos|"
    r"watermark|lettering|letters|words|slogan|headline|label|labels|signage|sign|signs|poster|"
    r"posters|banner|quote|quotes|hashtag|thumbnail|shorts|short-form|layout|overlay|"
    r"aspect ratio|vertical format|vertical frame|portrait format)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"^\s*(?:no|without|not|never|avoid|없는|없이)\b", re.IGNORECASE)
_QUOTED = re.compile(r"[\"“”'‘’][^\"“”'‘’]{1,80}[\"“”'‘’]")


def clean_image_prompt(text: str) -> str:
    """쉼표로 나눈 조각 중 글자·레이아웃·부정문 조각을 빼고 다시 잇는다."""
    text = _QUOTED.sub("", text)
    parts = re.split(r"[,，;]|(?<=[a-z])\.\s", text)
    out: list[str] = []
    for part in parts:
        part = part.strip(" .")
        if not part or _TEXT_TERMS.search(part) or _NEGATION.search(part):
            continue
        if part.lower() not in {p.lower() for p in out}:
            out.append(part)
    return ", ".join(out)


def visual_style(style_seed: str) -> str:
    """style_seed에서 그림에 쓸 수 있는 부분(색감·조명·분위기)만 남긴다."""
    return clean_image_prompt(style_seed)


def build_prompt(scene_prompt: str, style: str, *, quality: bool = True) -> str:
    """장면 프롬프트 + 공통 스타일 + 품질 문구 → 깨끗한 최종 프롬프트."""
    pieces = [scene_prompt, style]
    if quality:
        pieces.append(QUALITY)
    return clean_image_prompt(", ".join(p for p in pieces if p))
