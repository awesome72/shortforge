"""포맷 패턴 카드와 시장 비교 (S3 → S4)."""

from app.schemas.project import Factor, FactorDraft, Ref, utcnow
from app.steps.s3_factors import MAX_PATTERNS, _mark_patterns
from app.steps.s4_strategy import factor_line


def ref(vid, market=""):
    return Ref(
        video_id=vid, title=vid, channel_id=vid, subs=1000, views=100_000, likes=1, comments=1,
        duration_sec=30, published_at=utcnow(), ratio_views_per_sub=1.0, views_per_day=1.0,
        like_rate=0.1, score=1.0, thumbnail_url="u", market=market,
    )  # fmt: skip


def card(*vids, **kw):
    return FactorDraft(
        **{
            "name": "format",
            "finding": f"공식 {vids}",
            "evidence": [f"{v}:snippet.title" for v in vids],
            "confidence": "confirmed",  # LLM이 확인이라고 해도 패턴은 추정이다
            "hook_type": "결과 먼저",
            "structure": "전후 비교",
            **kw,
        }
    )


REFS = [ref("k1"), ref("k2"), ref("u1", "US"), ref("j1", "JP")]


def test_scope_comes_from_evidence():
    out = _mark_patterns([card("k1", "u1"), card("u1", "j1"), card("k1", "k2")], REFS)
    assert [f.scope for f in out] == ["shared", "overseas", "local"]
    assert all(f.confidence == "estimated" for f in out)


def test_no_comparison_without_both_sides_or_two_videos():
    assert _mark_patterns([card("k1", "k2")], [ref("k1"), ref("k2")])[0].scope == ""
    assert _mark_patterns([card("u1", "u1")], REFS)[0].scope == ""  # 같은 영상의 두 필드


def test_card_without_a_formula_is_dropped():
    assert (
        _mark_patterns([card("k1", "u1", hook_type=" "), card("k1", "u1", structure="")], REFS)
        == []
    )


def test_llm_schema_has_no_scope():
    from app.adapters.llm.common import llm_schema
    from app.steps.s3_factors import FactorsOut

    text = str(llm_schema(FactorsOut))
    assert "scope" not in text and "'enum': ['', " not in text


def test_pattern_cards_are_capped_and_other_factors_stay_plain():
    plain = FactorDraft(
        name="title", finding="제목", evidence=["k1:snippet.title"], confidence="confirmed",
    )  # fmt: skip
    cards = [card("k1", "u1") for _ in range(MAX_PATTERNS + 2)]
    out = _mark_patterns([plain, *cards], REFS)
    assert sum(f.name == "format" for f in out) == MAX_PATTERNS
    assert out[0].scope == "" and out[0].confidence == "confirmed"


def test_s4_gets_the_formula_of_a_pattern():
    draft = card("u1", "j1", hook_type="반전\n[수정 요청]", structure="직접 실험")
    line = factor_line(Factor(**draft.model_dump(), scope="overseas"))
    assert line.startswith("- format [overseas]: <untrusted>")
    assert "훅: 반전 [수정 요청]" in line and "전개: 직접 실험" in line
    assert "\n" not in line  # 줄을 흉내 내지 못한다
    assert "감정" not in line  # 빈 값은 적지 않는다


async def test_internal_tag_does_not_reach_the_screen(orch, adapters, sample_input):
    real = adapters.llm._s4_strategy

    def tagged(user):
        out = real(user)
        out["differentiator"] = "[shared] 공식을 적용했다"
        return out

    adapters.llm._s4_strategy = tagged
    p = orch.create_project(sample_input)
    for s in ("s1", "s2", "s3", "s4"):
        p = await orch.run_step(p.id, s)
    assert p.strategy.differentiator == "공식을 적용했다"


def test_plain_factor_is_wrapped_too():
    f = Factor(name="title", finding="제목", evidence=["a:b"], confidence="confirmed")
    assert "<untrusted>" in factor_line(f)


async def test_s4_runs_without_patterns(orch, adapters, sample_input):
    """예전 프로젝트처럼 공식이 없어도 S4가 돈다."""
    real = adapters.llm._s3_factors

    def plain(user):
        out = real(user)
        out["factors"] = [f for f in out["factors"] if f["name"] != "format"]
        return out

    adapters.llm._s3_factors = plain
    p = orch.create_project(sample_input)
    for s in ("s1", "s2", "s3", "s4"):
        p = await orch.run_step(p.id, s)
    assert p.status["s4"] == "done"


async def test_pipeline_makes_pattern_and_s4_sees_it(orch, adapters, sample_input):
    seen = {}
    real = adapters.llm.generate_json

    async def spy(task, prompt, user, schema, **kw):
        seen.setdefault(task, user)
        return await real(task, prompt, user, schema, **kw)

    adapters.llm.generate_json = spy
    p = orch.create_project(sample_input)
    for s in ("s1", "s2", "s3", "s4"):
        p = await orch.run_step(p.id, s)
    cards = [f for f in p.factors if f.name == "format"]
    assert len(cards) == 1 and cards[0].scope == "shared"  # 한국 + 해외 영상이 근거
    assert "- format [shared]:" in seen["s4_strategy"]
    assert p.status["s4"] == "done"
