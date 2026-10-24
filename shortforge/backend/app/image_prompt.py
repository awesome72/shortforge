"""이미지 생성 프롬프트 다듬기 (S5·장면 이미지 다시 만들기·후보 공통).

실측(2026-10-21): S4의 style_seed("…, 굵은 흰색 자막, 세로 9:16 숏폼 스타일")를 그대로 붙였더니
FLUX가 장면마다 큰 영문 문구("Start Writing Your Story.", "Agreement in Progress")를 그려 넣었다.
style_seed는 영상(자막·레이아웃) 스타일이지 그림 묘사가 아니다. 또 FLUX에는 negative 입력이 없고,
"no face shown"·"no text" 같은 부정문은 오히려 그 대상을 그리게 만든다.

그래서
- 글자를 부르는 말(자막·제목·로고·포스터·간판, 따옴표 속 문구)과 화면비·레이아웃 말(9:16, 숏폼),
  부정문 조각을 프롬프트에서 뺀다. 마지막 요청 직전에도 한 번 더 거른다
  (예전 프로젝트의 다시 만들기 대비).
- 품질 문구를 붙인다. 그림체에 맞춰 고른다: 스타일이 일러스트인데 "documentary photograph,
  35mm lens"를 붙였더니 같은 영상 안에서 일러스트와 사진풍이 섞였다(2026-10-24, 제2의 인생 영상).
- 주인공 묘사(subject)에 성별이 없으면("a Korean person in their 50s") 장면마다 다른 사람이
  나왔다. fix_subject()가 성별을 채우고, 장면 프롬프트 속 묘사도 같은 문구로 맞춘다.
"""

from __future__ import annotations

import re

# 생성 이미지 프롬프트 규칙이 바뀌면 올린다.
# 이보다 낮은 생성 이미지는 S5를 다시 실행할 때 새로 만든다
# 2: 자막·화면비·부정문 제거, 864×1536 / 3: 주인공 고정(subject)·지역에 맞는 인물·얼굴 장면 줄이기
# 4: 그림체별 품질 문구, 주인공 성별 고정
PROMPT_REV = 4

QUALITY_PHOTO = (
    "candid documentary photograph, natural light, shallow depth of field, 35mm lens, fine detail"
)
QUALITY_ILLUSTRATION = (
    "refined editorial illustration, cohesive palette, soft gradients, clean confident linework, "
    "gentle diffused light, fine detail"
)
QUALITY_CINEMATIC = (
    "cinematic film still, shallow depth of field, 50mm lens, subtle film grain, fine detail"
)
QUALITY = QUALITY_PHOTO  # 예전 이름 (사진이 기본)

# 1단계에서 고르는 그림체 → 모든 장면에 붙는 영문 스타일 (auto면 4단계 스타일을 따른다)
VISUAL_STYLES = {
    "photo": "natural documentary photography, soft daylight, true-to-life color",
    "cinematic": "cinematic film look, moody contrast, warm highlights and teal shadows",
    "illustration": "refined editorial illustration, warm muted palette, clean simple shapes",
    "watercolor": "soft watercolor painting, delicate washes, textured paper",
}
_MEDIUM = re.compile(
    r"photo|photograph|film|cinematic|render|realistic|illustrat|watercolou?r|painting|drawing|"
    r"sketch|anime|cartoon|vector|comic",
    re.IGNORECASE,
)
_ILLUSTRATED = re.compile(
    r"illustrat|watercolou?r|anime|cartoon|drawing|drawn|painting|painted|sketch|vector|"
    r"flat design|3d render|clay|pastel art|comic|"
    r"일러스트|수채|그림체|만화|애니|드로잉|회화|스케치",
    re.IGNORECASE,
)

_GENDERED = re.compile(r"\b(?:woman|man|women|men|girl|boy|female|male|lady|gentleman)\b", re.I)
_PERSON = re.compile(r"\b(?:person|individual|adult|people)\b", re.I)
_FEMALE_HINT = re.compile(r"여성|여자|엄마|주부|아내|딸|언니|누나|할머니|워킹맘|신부|여대생|여고생")
_MALE_HINT = re.compile(r"남성|남자|아빠|남편|아들|형|오빠|할아버지|신랑|남대생|남고생")

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


def is_illustrated(style: str) -> bool:
    return bool(_ILLUSTRATED.search(style or ""))


def quality_for(style: str) -> str:
    """그림체에 맞는 품질 문구 (일러스트에 사진·렌즈 문구를 붙이면 장면마다 그림체가 섞인다)."""
    if is_illustrated(style):
        return QUALITY_ILLUSTRATION
    if re.search(r"cinematic", style or "", re.IGNORECASE):
        return QUALITY_CINEMATIC
    return QUALITY_PHOTO


def apply_visual_style(style: str, choice: str) -> str:
    """사용자가 고른 그림체를 앞에 두고, LLM 스타일에서는 색감·조명만 남긴다 (그림체 말은 뺀다)."""
    preset = VISUAL_STYLES.get(choice)
    if not preset:
        return style
    keep = [p.strip() for p in (style or "").split(",") if p.strip() and not _MEDIUM.search(p)]
    return ", ".join([preset, *keep])


def build_prompt(scene_prompt: str, style: str, *, quality: bool = True) -> str:
    """장면 프롬프트 + 공통 스타일 + 품질 문구 → 깨끗한 최종 프롬프트."""
    pieces = [scene_prompt, style]
    if quality:
        pieces.append(quality_for(style))
    return clean_image_prompt(", ".join(p for p in pieces if p))


def fix_subject(subject: str, audience: str, seed: int) -> str:
    """주인공 묘사에 성별이 없으면 채운다.

    타깃에 성별 단서(엄마·남편 등)가 있으면 그것을, 없으면 seed로 정한다(같은 프로젝트는 같은 결과).
    """
    subject = " ".join((subject or "").split())
    if not subject or _GENDERED.search(subject):
        return subject
    if _FEMALE_HINT.search(audience or ""):
        gender = "woman"
    elif _MALE_HINT.search(audience or ""):
        gender = "man"
    else:
        gender = "woman" if seed % 2 == 0 else "man"
    if _PERSON.search(subject):
        return _PERSON.sub(gender, subject, count=1)
    return f"{subject}, a {gender}"


def apply_subject(prompt: str, raw_subject: str, subject: str) -> str:
    """장면 프롬프트에 들어간 (성별 없는) 주인공 묘사를 고친 묘사로 바꾼다."""
    if raw_subject and subject and raw_subject != subject and raw_subject in prompt:
        return prompt.replace(raw_subject, subject)
    if subject and _PERSON.search(prompt) and not _GENDERED.search(prompt):
        gender = _GENDERED.search(subject)
        if gender:
            return _PERSON.sub(gender.group(0), prompt, count=1)
    return prompt
