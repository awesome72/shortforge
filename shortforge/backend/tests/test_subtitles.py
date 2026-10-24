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


def test_split_keeps_meaning_units_together():
    """수·관형사·꾸미는 말 뒤에서 줄을 바꾸지 않는다 (2026-10-24 실제 영상: "적은 한 / 장이")."""

    def lines(text):
        return [c.text for c in cues_from_text(text, 5.0, 14)]

    assert lines("이렇게 적은 한 장이 제2의 인생 로드맵이 됩니다.") == [
        "이렇게 적은 한 장이",
        "제2의 인생",
        "로드맵이 됩니다",
    ]
    assert lines("생활비와 건강 같은 현실도 함께 점검하고") == [
        "생활비와 건강 같은 현실도",
        "함께 점검하고",
    ]
    assert lines("괜찮아요, 많은 분들이 같은 마음이에요.") == [
        "괜찮아요",
        "많은 분들이",
        "같은 마음이에요",
    ]
    # 서수("두 번째 / 인생")도 뒷말과 함께 둔다 (2026-10-24 재렌더에서 발견)
    # 한 줄을 더 쓰더라도 "두 / 번째"로 끊지 않는다
    assert lines("작은 계획 하나가 두 번째 인생의 첫걸음이에요.") == [
        "작은 계획 하나가",
        "두 번째 인생의",
        "첫걸음이에요",
    ]
    # 한 줄 안에 합쳐진 나열은 쉼표를 남긴다
    assert lines("다음은 건강, 돈, 관계를 하나씩 점검해요.")[0] == "다음은 건강, 돈"
