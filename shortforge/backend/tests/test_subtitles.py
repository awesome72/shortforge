from app.subtitles import (
    Cue,
    Word,
    cues_from_text,
    cues_from_words,
    group_tokens,
    shift,
    to_ass,
    to_srt,
)


def words(spec: str, gap: float = 0.05) -> list[Word]:
    out, t = [], 0.1
    for tok in spec.split():
        d = 0.08 * len(tok) + 0.1
        out.append(Word(tok, round(t, 3), round(t + d, 3)))
        t += d + gap
    return out


def texts(cues: list[Cue]) -> list[str]:
    return [c.text for c in cues]


def test_breaks_at_punctuation_from_source_text():
    src = "3개월 전의 저는, 계단 두 층에도 숨이 찼어요."
    ws = words("3개월 전의 저는 계단 두 층에도 숨이 찼어요")
    assert texts(cues_from_words(ws, 14, source_text=src)) == [
        "3개월 전의 저는",
        "계단 두 층에도",
        "숨이 찼어요",
    ]


def test_long_phrase_split_balanced_without_orphan():
    src = "그래서 딱 10분만 하기로 했어요."
    ws = words("그래서 딱 10분만 하기로 했어요")
    assert texts(cues_from_words(ws, 14, source_text=src)) == ["그래서 딱 10분만", "하기로 했어요"]


def test_short_phrase_merged_into_neighbor():
    tokens = ["스쿼트", "플랭크", "런지", "이", "세", "가지만요"]
    breaks = [True, True, True, False, False, True]
    groups = group_tokens(tokens, breaks, 14)
    lines = [" ".join(tokens[i] for i in g) for g in groups]
    assert all(len(line) <= 14 for line in lines)
    assert "런지" not in lines  # 짧은 구절이 혼자 남지 않는다


def test_every_line_within_limit_and_order_preserved():
    src = "석 달이 지난 지금은, 아침에 일어나는 게 확실히 가벼워졌어요."
    tokens = src.replace(",", "").replace(".", "").split()
    cues = cues_from_words(words(" ".join(tokens)), 14, source_text=src)
    assert " ".join(texts(cues)).split() == tokens
    assert all(len(t) <= 14 for t in texts(cues))


def test_single_overlong_word_kept_whole():
    cues = cues_from_words(words("가나다라마바사아자차카타파하거너"), 14)
    assert texts(cues) == ["가나다라마바사아자차카타파하거너"]


def test_long_silence_starts_new_cue():
    ws = [Word("하나", 0.0, 0.3), Word("둘", 1.5, 1.8)]
    assert texts(cues_from_words(ws, 14)) == ["하나", "둘"]


def test_cues_bridge_small_gaps_and_min_duration():
    ws = [Word("가나다라마", 0.0, 0.2), Word("바사아자차", 0.25, 0.4)]
    cues = cues_from_words(ws, 5)
    assert cues[0].end == cues[1].start  # 0.05초 공백은 메운다
    assert cues[1].end - cues[1].start >= 0.5


def test_text_fallback_distributes_duration():
    cues = cues_from_text("퇴근하고 나면 너무 지쳐서, 운동은 늘 내일로 미뤘죠.", 4.0, 14)
    assert texts(cues) == ["퇴근하고 나면 너무 지쳐서", "운동은 늘 내일로 미뤘죠"]
    assert cues[0].start == 0 and abs(cues[-1].end - 4.0) < 1e-9


def test_srt_and_ass_format():
    cues = shift([Cue(0.0, 1.234, "안녕 {x}", "hook_bold")], 61.0)
    srt = to_srt(cues)
    assert "00:01:01,000 --> 00:01:02,234" in srt
    ass = to_ass(cues, 1080, 1920, "Malgun Gothic")
    assert "Dialogue: 0,0:01:01.00,0:01:02.23,hook_bold,,0,0,0,,안녕 (x)" in ass
    assert "Style: hook_bold,Malgun Gothic,100" in ass
