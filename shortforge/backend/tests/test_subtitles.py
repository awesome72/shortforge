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
    assert r"Dialogue: 1,0:01:01.00,0:01:02.23,hook_bold,,0,0,0,,{\blur2" in ass
    assert ass.rstrip().endswith("안녕 (x)")
    assert "Style: hook_bold,Malgun Gothic,104" in ass


def test_ass_accents_numbers_only():
    """숫자가 든 어절만 포인트 색(#E6B460), 강조 자막은 전체가 포인트 색이라 그대로."""
    ass = to_ass(
        [Cue(0, 1, "퇴근 후 10분 홈트", "body"), Cue(1, 2, "3개월 뒤", "emphasis")],
        1080,
        1920,
        "Noto Sans KR",
    )
    assert r"퇴근 후 {\1c&H60B4E6&}10분{\1c&HFFFFFF&} 홈트" in ass
    assert r",emphasis,,0,0,0,,{\blur1.5\fad(90,60)\fscx96" in ass
    assert r"{\1c&H60B4E6&}3개월" not in ass


def test_pick_font_prefers_installed_and_respects_setting(tmp_path):
    from app.subtitles import find_font, pick_font

    (tmp_path / "NanumGothicBold.ttf").write_bytes(b"x")
    assert pick_font("auto", [tmp_path]) == "NanumGothic"
    (tmp_path / "NotoSansKR-Bold.ttf").write_bytes(b"x")
    family, path = find_font("auto", [tmp_path])
    assert family == "Noto Sans KR" and path == tmp_path / "NotoSansKR-Bold.ttf"
    # 예전 기본값(Malgun Gothic)도 자동으로 고른다. 다른 이름을 직접 정했으면 그대로
    assert pick_font("Malgun Gothic", [tmp_path]) == "Noto Sans KR"
    assert find_font("My Brand Font", [tmp_path]) == ("My Brand Font", None)
    assert pick_font("auto", []) == "Malgun Gothic"


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


def test_badge_number_reads_ordinals():
    from app.subtitles import badge_number

    assert badge_number("첫째, 종이에 적어 보세요") == 1
    assert badge_number("둘째 생활비도 점검해요") == 2
    assert badge_number("세 번째는 건강이에요") == 3
    assert badge_number("2단계: 기록하기") == 2
    assert badge_number("3. 매일 10분") == 3
    assert badge_number("첫걸음이에요") is None  # '첫'으로 시작해도 순서가 아니면 배지 없음
    assert badge_number("10분이면 충분해요") is None
