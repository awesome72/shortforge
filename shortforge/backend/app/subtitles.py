"""자막: 어절 타이밍 → 자막 큐 → SRT / ASS (PROJECT_PLAN G3).

대사 텍스트를 이미 알고 있으므로 Whisper 없이 TTS 단어 타이밍으로 자막을 만든다.
타이밍이 없으면 글자 수 비율로 음성 길이에 나눠 배치한다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

SENTENCE_GAP_SEC = 0.6  # 어절 사이가 이만큼 비면 새 자막
MIN_CUE_SEC = 0.5
BRIDGE_GAP_SEC = 0.3  # 이보다 짧은 공백은 앞 자막을 늘려 깜빡임을 없앤다


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Cue:
    start: float
    end: float
    text: str
    style: str = "body"


PUNCT = ",.!?…~;:"
MIN_PHRASE_CHARS = 4  # 이보다 짧은 구절은 이웃 구절에 붙여 고아 자막을 막는다


def cues_from_words(
    words: list[Word], max_chars: int, style: str = "body", source_text: str | None = None
) -> list[Cue]:
    """어절 타이밍으로 자막을 만든다.

    TTS 타이밍에는 문장부호가 없으므로 source_text(원문 대사)에서 쉼표·마침표 위치를 찾아
    그 자리에서 우선 끊는다. 한 구절이 max_chars를 넘으면 글자 수가 고르게 나눈다.
    """
    if not words:
        return []
    breaks = _punct_breaks([w.text for w in words], source_text or "")
    hard = [False] * len(words)
    for i in range(1, len(words)):
        if words[i].start - words[i - 1].end > SENTENCE_GAP_SEC:
            breaks[i - 1] = hard[i - 1] = True
    tokens = [w.text for w in words]
    groups = group_tokens(tokens, breaks, max_chars, hard)
    cues = [
        Cue(words[g[0]].start, words[g[-1]].end, _join(tokens, g, breaks), style) for g in groups
    ]
    return _smooth(cues)


def cues_from_text(text: str, duration: float, max_chars: int, style: str = "body") -> list[Cue]:
    """타이밍이 없을 때: 같은 규칙으로 묶고 글자 수 비율로 시간을 나눈다."""
    raw = text.split()
    breaks = [bool(t) and t[-1] in PUNCT for t in raw]
    tokens = [t.rstrip(",.") or t for t in raw]
    chunks = [_join(tokens, g, breaks) for g in group_tokens(tokens, breaks, max_chars)]
    total = sum(len(c) for c in chunks) or 1
    cues, t = [], 0.0
    for c in chunks:
        d = duration * len(c) / total
        cues.append(Cue(t, t + d, c, style))
        t += d
    return cues


def _join(tokens: list[str], group: list[int], breaks: list[bool]) -> str:
    """한 줄 안에서 구절이 바뀌는 자리에는 쉼표를 남긴다 ("다음은 건강, 돈"). 줄 끝은 쉼표 없이."""
    return " ".join(
        tokens[i] + ("," if breaks[i] and i != group[-1] and tokens[i][-1:] not in PUNCT else "")
        for i in group
    )


def _punct_breaks(tokens: list[str], source: str) -> list[bool]:
    """원문에서 각 토큰을 차례로 찾아, 바로 뒤에 문장부호가 오면 True."""
    breaks = [False] * len(tokens)
    cursor = 0
    for i, tok in enumerate(tokens):
        idx = source.find(tok, cursor)
        if idx < 0:
            continue
        end = idx + len(tok)
        breaks[i] = end < len(source) and source[end] in PUNCT
        cursor = end
    return breaks


def _len(tokens: list[str], idx: list[int]) -> int:
    return len(" ".join(tokens[i] for i in idx))


def group_tokens(
    tokens: list[str], breaks: list[bool], max_chars: int, hard: list[bool] | None = None
) -> list[list[int]]:
    """토큰 인덱스를 자막 줄 단위로 묶는다.

    1) 문장부호(breaks)에서 구절을 나눈다.
    2) 아주 짧은 구절은 앞 구절과 합친다 — 합쳐도 max_chars 이하이고, 그 사이가 침묵(hard)이
       아닐 때만. 침묵을 건너 합치면 아직 말하지 않은 말이 먼저 화면에 뜬다.
    3) max_chars를 넘는 구절은 줄 수를 최소로, 그 안에서 가장 긴 줄이 가장 짧도록 나눈다.
    """
    hard = hard or [False] * len(tokens)
    phrases: list[list[int]] = [[]]
    for i in range(len(tokens)):
        phrases[-1].append(i)
        if breaks[i] and i < len(tokens) - 1:
            phrases.append([])

    merged: list[list[int]] = []
    for ph in phrases:
        if (
            merged
            and not hard[merged[-1][-1]]
            and (_len(tokens, ph) < MIN_PHRASE_CHARS or _len(tokens, merged[-1]) < MIN_PHRASE_CHARS)
        ):
            if _len(tokens, merged[-1] + ph) <= max_chars:
                merged[-1] += ph
                continue
        merged.append(ph)

    groups: list[list[int]] = []
    for ph in merged:
        groups.extend(_balanced_split(tokens, ph, max_chars))
    return groups


# 줄을 이 어절 뒤에서 끊으면 뜻이 갈린다: 수·관형사("한 / 장", "이 / 방법"),
# 꾸미는 말("건강 같은 / 현실"), 소유격("제2의 / 인생").
# 2026-10-24 실제 영상에서 "이렇게 적은 한 / 장이 제2의 인생"으로 끊겼다
_BINDS_NEXT = {
    "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열", "몇", "첫", "단", "온",
    "이", "그", "저", "이런", "그런", "저런", "어떤", "모든", "각", "새", "옛", "매", "총", "약",
}  # fmt: skip
_BINDS_NEXT_END = ("같은", "적인", "싶은", "있는", "없는", "하는", "되는", "했던", "하던", "째")
_WEAK_NEXT_END = ("와", "과", "랑", "및", "의")  # "인생의 / 첫걸음"은 읽을 만하다
# 앞말에 붙어 다니는 말: 이 앞에서 끊지 않는다 ("할 / 수", "그럴 / 때")
_BINDS_PREV = {"처럼", "만큼", "정도", "때", "것", "수", "줄", "등", "뿐", "중"}
# "같은"은 앞말에 붙기도("건강 같은 현실") 뒷말을 꾸미기도("같은 마음") 해서 약하게만 막는다
_WEAK_PREV = {"같은", "같이"}
# 뒷말을 꾸미는 끝말 ("많은 / 분들", "새로운 / 시작").
# 조사 "만"·"을"처럼 받침만 같은 말은 넣지 않는다
_ADNOMINAL_END = ("은", "는", "던", "운", "할", "될")
BIND_PENALTY = 4  # 글자 수로 환산한 감점 (강한 감점 8 = 한 줄이 8자 길어지는 것과 같다)
EXTRA_LINE_COST = 6  # 뜻이 갈리는 걸 피하려고 한 줄을 더 쓸 때의 감점
MAX_BRUTE_TOKENS = 16


def _cut_penalty(tokens: list[str], left: int, right: int) -> int:
    """tokens[left]와 tokens[right] 사이에서 줄을 바꿀 때의 감점."""
    a = tokens[left].rstrip(PUNCT)
    b = tokens[right].rstrip(PUNCT)
    if a in _BINDS_NEXT or a.isdigit() or a.endswith(_BINDS_NEXT_END) or b in _BINDS_PREV:
        return 2 * BIND_PENALTY
    if a.endswith(_WEAK_NEXT_END) or b in _WEAK_PREV or _adnominal(a):
        return BIND_PENALTY
    return 0


def _adnominal(word: str) -> bool:
    """뒷말을 꾸미는 꼴로 끝나는 말("많은", "적은", "할"): 대개 뒷말을 꾸민다.

    주제를 나타내는 '은/는'도 섞여 있어 약하게만 막는다.
    """
    return len(word) >= 2 and word.endswith(_ADNOMINAL_END)


def _balanced_split(tokens: list[str], idx: list[int], max_chars: int) -> list[list[int]]:
    """max_chars를 넘는 구절을 줄 수를 최소로 나눈다.

    같은 줄 수 안에서는 (가장 긴 줄 길이 + 뜻이 갈리는 자리 감점)이 가장 작은 방법을 고른다.
    """
    if _len(tokens, idx) <= max_chars or len(idx) == 1:
        return [idx]
    # 한 어절이 max_chars보다 길면 그 어절 길이를 한도로 삼는다 (k=n이면 항상 가능)
    limit = max(max_chars, *(len(tokens[i]) for i in idx))
    n = len(idx)
    if n > MAX_BRUTE_TOKENS:
        return _dp_split(tokens, idx, limit)
    # 가장 적은 줄 수(k_min)와 한 줄 더(k_min+1)를 함께 보고 고른다:
    # "작은 계획 하나가 두 / 번째 …"보다 "작은 계획 하나가 / 두 번째 인생의 / 첫걸음이에요"가 낫다
    best: tuple[float, float] | None = None
    best_parts: list[list[int]] = []
    k_min = None
    for k in range(2, n + 1):
        if k_min is not None and k > k_min + 1:
            break
        for cuts in combinations(range(1, n), k - 1):
            bounds = (0, *cuts, n)
            parts = [idx[bounds[g] : bounds[g + 1]] for g in range(k)]
            lens = [_len(tokens, p) for p in parts]
            if max(lens) > limit:
                continue
            if k_min is None:
                k_min = k
            pen = sum(_cut_penalty(tokens, idx[c - 1], idx[c]) for c in cuts)
            pen += EXTRA_LINE_COST * (k - k_min)
            score = (max(lens) + pen, max(lens) - min(lens))  # 동점이면 줄 길이가 고른 쪽
            if best is None or score < best:
                best, best_parts = score, parts
    if best is None:
        raise AssertionError("unreachable")
    return best_parts


def _dp_split(tokens: list[str], idx: list[int], limit: int) -> list[list[int]]:
    """어절이 아주 많을 때: 가장 긴 줄만 줄이는 동적 계획법 (감점 없이)."""
    n = len(idx)
    for k in range(2, n + 1):
        # best[j][g] = 앞 j개 토큰을 g줄로 나눌 때 가장 긴 줄 길이의 최솟값
        inf = float("inf")
        best = [[inf] * (k + 1) for _ in range(n + 1)]
        cut = [[0] * (k + 1) for _ in range(n + 1)]
        best[0][0] = 0
        for j in range(1, n + 1):
            for g in range(1, min(j, k) + 1):
                for s in range(g - 1, j):
                    cand = max(best[s][g - 1], _len(tokens, idx[s:j]))
                    if cand < best[j][g]:
                        best[j][g], cut[j][g] = cand, s
        if best[n][k] <= limit:
            parts, j = [], n
            for g in range(k, 0, -1):
                s = cut[j][g]
                parts.append(idx[s:j])
                j = s
            return parts[::-1]
    raise AssertionError("unreachable")


def _smooth(cues: list[Cue]) -> list[Cue]:
    """최소 표시 시간을 보장하되, 다음 자막과 겹치거나 짧게 끊기지 않게 맞춘다."""
    for c in cues:
        c.end = max(c.end, c.start + MIN_CUE_SEC)
    for cur, nxt in zip(cues, cues[1:], strict=False):
        if nxt.start - cur.end < BRIDGE_GAP_SEC:  # 겹침(음수)도 여기서 정리된다
            cur.end = nxt.start
    return cues


def shift(cues: list[Cue], offset: float) -> list[Cue]:
    return [Cue(c.start + offset, c.end + offset, c.text, c.style) for c in cues]


# ── 출력 형식 ─────────────────────────────────────────────


def _srt_time(t: float) -> str:
    ms = round(max(t, 0) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{i}\n{_srt_time(c.start)} --> {_srt_time(c.end)}\n{c.text}\n"
        for i, c in enumerate(cues, 1)
    ]
    return "\n".join(blocks)


def _ass_time(t: float) -> str:
    cs = round(max(t, 0) * 100)
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


# 색상은 &HAABBGGRR(AA=00 불투명). 하단 여백(MarginV)은 Shorts UI(제목·버튼)에 가리지 않게 둔다.
# 디자인(2026-10-24): 굵은 흰 글자 + 반투명 테두리·부드러운 그림자,
# 포인트 색은 텅스텐(#E6B460) 하나.
# 예전 노란 글자(#FFE600)는 유튜브 기본 자막처럼 보였다. 훅은 화면 위쪽 3분의 1에 큰 제목으로 둔다.
WHITE = "&H00FFFFFF"
ACCENT = "&H0060B4E6"  # #E6B460 (웹 화면 accent와 같은 색)
OUTLINE = "&H50101010"
OUTLINE_WARM = "&H20183A5A"  # #5A3A18 짙은 갈색 (강조 자막 테두리)
SHADOW = "&H9A000000"
ASS_STYLES = {
    #            크기 굵게  글자색  위치 MarginV 테두리
    "body": (80, -1, WHITE, 2, 500, 4),
    # 강조: 밝은 배경에서 텅스텐 글자가 묻혀(2026-10-24 재렌더) 흰 글자 + 짙은 갈색 테두리로 둔다
    "emphasis": (88, -1, WHITE, 2, 500, 6),
    "hook_bold": (104, -1, WHITE, 8, 300, 5),  # 위쪽 가운데 (상태 표시줄 아래)
    # 화면 장식 (SRT에는 넣지 않는다): 단계 번호 배지(왼쪽 위 상자), 엔딩 카드의 채널 이름(가운데)
    "badge": (64, -1, ACCENT, 7, 250, 16),
    "brand": (72, -1, WHITE, 5, 0, 4),
    "dim": (10, 0, WHITE, 7, 0, 0),  # 엔딩 카드 뒤 화면을 어둡게 (글자 대신 사각형을 그린다)
    # 커버(썸네일) 제목: 아래쪽 1/3 (인물 얼굴은 대개 위쪽에 있다)
    "cover": (100, -1, WHITE, 2, 420, 6),
}
BOX_STYLES = {"badge"}  # 글자 뒤에 반투명 상자 (BorderStyle 3: 테두리 색이 상자 색)
BOX_COLOUR = "&H38101010"
# 등장 효과: 짧게 나타나고, 훅은 살짝 커지며 자리 잡는다
ASS_INTRO = {
    "body": r"{\blur1.5\fad(90,60)}",
    "emphasis": r"{\blur1.5\fad(90,60)\fscx96\fscy96\t(0,160,\fscx100\fscy100)}",
    "hook_bold": r"{\blur2\fad(150,80)\fscx92\fscy92\t(0,240,\fscx100\fscy100)}",
    "badge": r"{\fad(180,120)}",
    "brand": r"{\blur1\fad(350,0)\fscx94\fscy94\t(0,500,\fscx100\fscy100)}",
}
_ORDINAL_WORDS = {
    "첫째": 1, "둘째": 2, "셋째": 3, "넷째": 4, "다섯째": 5,
    "첫": 1, "두": 2, "세": 3, "네": 4, "다섯": 5,
}  # fmt: skip
_ORDINAL = re.compile(
    r"^\s*(?:(첫째|둘째|셋째|넷째|다섯째)|(첫|두|세|네|다섯)\s*번째|(\d{1,2})\s*(?:[.)]|단계|번째))"
)


def badge_number(text: str) -> int | None:
    """대사가 "첫째,", "두 번째", "3단계"처럼 순서로 시작하면 그 번호 (번호 배지용)."""
    m = _ORDINAL.match(text or "")
    if not m:
        return None
    if m.group(3):
        return int(m.group(3))
    return _ORDINAL_WORDS[m.group(1) or m.group(2)]


_HAS_DIGIT = re.compile(r"\d")


def _dim_rect(width: int, height: int) -> str:
    """화면 전체를 덮는 반투명 검은 사각형 (서서히 어두워진다)."""
    return (
        r"{\an7\pos(0,0)\p1\bord0\shad0\1c&H000000&\1a&H70&\fad(400,0)}"
        f"m 0 0 l {width} 0 l {width} {height} l 0 {height}" + r"{\p0}"
    )


def _accent_numbers(text: str, style: str) -> str:
    """숫자가 든 어절("10분", "3개월")만 포인트 색으로 칠한다 (강조 자막은 테두리로 구분)."""
    if style == "emphasis":
        return text
    # 줄바꿈(\N)도 어절 경계다: 공백으로만 나누면 "30년,\N나만의"가 한 어절로 칠해졌다
    return "\\N".join(
        " ".join(
            f"{{\\1c&H60B4E6&}}{w}{{\\1c&HFFFFFF&}}" if _HAS_DIGIT.search(w) else w
            for w in line.split(" ")
        )
        for line in text.split("\\N")
    )


ASS_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)


SIDE_MARGIN = 70  # 자막 좌우 여백(px). 이 안을 넘으면 libass가 줄을 하나 더 접는다


def _glyph_width(ch: str, size: int) -> float:
    """글자 폭 어림값(px): 한글·한자는 거의 정사각형, 공백은 좁다."""
    if ch == " ":
        return size * 0.3
    if ord(ch) >= 0x2E80:
        return size * 0.92
    return size * 0.58


COVER_MAX_CHARS = 10  # 커버 제목 한 줄 글자 수 (100px 한글 10자가 1080 화면 폭 안에 들어간다)


def wrap_title(title: str, max_chars: int = COVER_MAX_CHARS) -> str:
    """커버 제목을 뜻이 갈리지 않는 자리에서 줄바꿈한다 (자막과 같은 규칙).

    사용자가 "/"를 넣었으면 그 자리에서만 나눈다(커버 문구 직접 고치기).
    """
    if "/" in title:
        return "\n".join(part.strip() for part in title.split("/") if part.strip())
    tokens = title.split()
    if not tokens:
        return title
    breaks = [t[-1] in PUNCT for t in tokens]
    groups = group_tokens(tokens, breaks, max_chars)
    return "\n".join(" ".join(tokens[i] for i in g) for g in groups)


def too_wide(cues: list[Cue], width: int) -> list[str]:
    """화면 폭(좌우 여백 제외)을 넘을 것 같은 자막. 넘으면 한 줄이 더 생겨 장면을 가린다."""
    room = width - 2 * SIDE_MARGIN
    out: list[str] = []
    for c in cues:
        size = ASS_STYLES.get(c.style, ASS_STYLES["body"])[0]
        if any(sum(_glyph_width(ch, size) for ch in line) > room for line in c.text.split("\n")):
            out.append(c.text.replace("\n", " "))
    return out


def to_ass(cues: list[Cue], width: int, height: int, font: str) -> str:
    styles = "\n".join(
        f"Style: {name},{font},{size},{color},&H000000FF,"
        f"{BOX_COLOUR if name in BOX_STYLES else OUTLINE_WARM if name == 'emphasis' else OUTLINE},"
        f"{SHADOW},{bold},0,0,0,100,100,{2 if name == 'brand' else 0},0,"
        f"{3 if name in BOX_STYLES else 1},{outline},{0 if name in BOX_STYLES else 3},"
        f"{align},{SIDE_MARGIN},{SIDE_MARGIN},{margin_v},1"
        for name, (size, bold, color, align, margin_v, outline) in ASS_STYLES.items()
    )
    events = "\n".join(
        # 어둡게 하는 사각형은 맨 아래 층(0), 글자는 그 위(1)
        f"Dialogue: {0 if c.style == 'dim' else 1},{_ass_time(c.start)},{_ass_time(c.end)},"
        f"{c.style},,0,0,0,,"
        + (
            _dim_rect(width, height)
            if c.style == "dim"
            else ASS_INTRO.get(c.style, "") + _accent_numbers(_ass_escape(c.text), c.style)
        )
        for c in cues
    )
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
{ASS_STYLE_FORMAT}
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events}
"""


# ── 자막 글꼴 ─────────────────────────────────────────────

# 설치돼 있으면 이 순서로 쓴다. 글꼴 파일을 저장소에 넣지 않으므로 PC마다 있는 것을 고른다
FONT_CANDIDATES = (
    ("Pretendard", ("Pretendard-Bold.otf", "PretendardVariable.ttf", "Pretendard-Regular.otf")),
    ("Noto Sans KR", ("NotoSansKR-Bold.ttf", "NotoSansKR-VF.ttf", "NotoSansKR-Regular.ttf")),
    ("NanumGothic", ("NanumGothicBold.ttf", "NanumGothic.ttf")),
)
FALLBACK_FONT = "Malgun Gothic"


def font_dirs() -> list[Path]:
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    if os.environ.get("LOCALAPPDATA"):
        dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts")
    dirs += [Path("/usr/share/fonts"), Path.home() / ".fonts", Path("/Library/Fonts")]
    return dirs


def find_font(preferred: str, dirs: list[Path] | None = None) -> tuple[str, Path | None]:
    """(글꼴 이름, 글꼴 파일). SUBTITLE_FONT이 auto(또는 예전 기본값 Malgun Gothic)면
    설치된 글꼴 중 가장 나은 것을 고른다. 사용자 폴더에만 설치된 글꼴은 FFmpeg가 못 찾을 수 있어
    파일 경로도 함께 돌려준다(렌더가 작업 폴더에 복사해 fontsdir로 넘긴다).
    """
    if preferred and preferred not in ("auto", FALLBACK_FONT):
        return preferred, None
    for family, files in FONT_CANDIDATES:
        for d in dirs if dirs is not None else font_dirs():
            for f in files:
                if (d / f).is_file():
                    return family, d / f
    return FALLBACK_FONT, None


def pick_font(preferred: str, dirs: list[Path] | None = None) -> str:
    return find_font(preferred, dirs)[0]
