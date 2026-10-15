"""자막: 어절 타이밍 → 자막 큐 → SRT / ASS (PROJECT_PLAN G3).

대사 텍스트를 이미 알고 있으므로 Whisper 없이 TTS 단어 타이밍으로 자막을 만든다.
타이밍이 없으면 글자 수 비율로 음성 길이에 나눠 배치한다.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    groups = group_tokens([w.text for w in words], breaks, max_chars, hard)
    cues = [
        Cue(words[g[0]].start, words[g[-1]].end, " ".join(words[i].text for i in g), style)
        for g in groups
    ]
    return _smooth(cues)


def cues_from_text(text: str, duration: float, max_chars: int, style: str = "body") -> list[Cue]:
    """타이밍이 없을 때: 같은 규칙으로 묶고 글자 수 비율로 시간을 나눈다."""
    raw = text.split()
    breaks = [bool(t) and t[-1] in PUNCT for t in raw]
    tokens = [t.rstrip(",.") or t for t in raw]
    chunks = [" ".join(tokens[i] for i in g) for g in group_tokens(tokens, breaks, max_chars)]
    total = sum(len(c) for c in chunks) or 1
    cues, t = [], 0.0
    for c in chunks:
        d = duration * len(c) / total
        cues.append(Cue(t, t + d, c, style))
        t += d
    return cues


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


def _balanced_split(tokens: list[str], idx: list[int], max_chars: int) -> list[list[int]]:
    if _len(tokens, idx) <= max_chars or len(idx) == 1:
        return [idx]
    # 한 어절이 max_chars보다 길면 그 어절 길이를 한도로 삼는다 (k=n이면 항상 가능)
    limit = max(max_chars, *(len(tokens[i]) for i in idx))
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


# 색상은 &HAABBGGRR. 하단 여백(MarginV)은 Shorts UI(제목·버튼)에 가리지 않게 넉넉히 둔다.
ASS_STYLES = {
    #            크기 굵게  글자색       위치 MarginV
    "body": (72, 0, "&H00FFFFFF", 2, 520),
    "emphasis": (84, -1, "&H0000E6FF", 2, 520),
    "hook_bold": (100, -1, "&H0000E6FF", 5, 0),  # 화면 중앙
}


ASS_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)


def to_ass(cues: list[Cue], width: int, height: int, font: str) -> str:
    styles = "\n".join(
        f"Style: {name},{font},{size},{color},&H000000FF,&H00000000,&H64000000,"
        f"{bold},0,0,0,100,100,0,0,1,6,2,{align},60,60,{margin_v},1"
        for name, (size, bold, color, align, margin_v) in ASS_STYLES.items()
    )
    events = "\n".join(
        f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},{c.style},,0,0,0,,"
        + _ass_escape(c.text)
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
