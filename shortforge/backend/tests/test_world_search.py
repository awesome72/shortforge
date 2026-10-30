"""해외 시장까지 넓힌 레퍼런스 탐색 (D16)."""

from app.schemas.project import Ref, utcnow
from app.steps.s2_search import MIN_REF_VIEWS, _choose
from app.steps.s4_strategy import jaccard, title_tokens


def ref(vid, market="", channel=None, views=100_000):
    return Ref(
        video_id=vid, title=vid, channel_id=channel or vid, subs=1000, views=views, likes=1,
        comments=1, duration_sec=30, published_at=utcnow(), ratio_views_per_sub=1.0,
        views_per_day=1.0, like_rate=0.1, score=1.0, thumbnail_url="u", market=market,
    )  # fmt: skip


async def run_to(orch, sample_input, last):
    p = orch.create_project(sample_input)
    for s in ("s1", "s2", "s3", "s4", "s5", "s6", "s7"):
        p = await orch.run_step(p.id, s)
        if s == last:
            return p


async def test_s1_makes_keywords_for_each_market(orch, sample_input):
    p = await run_to(orch, sample_input, "s1")
    assert [w.lang for w in p.input.world_keywords] == ["en", "ja"]


async def test_s1_adds_world_keywords_without_touching_edited_keywords(orch, sample_input):
    sample_input.keywords = ["내가 고친 키워드"]
    p = await run_to(orch, sample_input, "s1")
    assert p.input.keywords == ["내가 고친 키워드"]
    assert p.input.world_keywords


async def test_s2_searches_each_market_with_its_language(orch, adapters, sample_input):
    seen = []
    real = adapters.youtube.search

    async def spy(keyword, region, lang, since, n):
        seen.append((keyword, region, lang))
        return await real(keyword, region, lang, since, n)

    adapters.youtube.search = spy
    p = await run_to(orch, sample_input, "s2")
    assert [(r, g) for _, r, g in seen] == [
        ("KR", "ko"), ("KR", "ko"), ("US", "en"), ("JP", "ja"),
    ]  # fmt: skip
    markets = {r.market for r in p.refs}
    assert markets == {"", "US", "JP"}
    selected = [r for r in p.refs if r.selected]
    assert len(selected) == 6
    assert sum(1 for r in selected if not r.market) == 3
    assert {r.market for r in selected if r.market} == {"US", "JP"}
    # 해외 영상만 한국어 제목을 받는다
    assert all(r.title_ko for r in p.refs if r.market and r.relevant is not None)
    assert not any(r.title_ko for r in p.refs if not r.market)


async def test_scores_are_compared_inside_each_market(orch, adapters, sample_input):
    """조회수 규모가 큰 시장이 후보를 독차지하지 않는다."""
    real = adapters.youtube.videos

    async def huge_in_us(ids):
        out = await real(ids)
        for v in out:
            if v.video_id in us:
                v.views *= 1000
        return out

    real_search = adapters.youtube.search
    us: set[str] = set()

    async def search(keyword, region, lang, since, n):
        ids = await real_search(keyword, region, lang, since, n)
        if region == "US":
            us.update(ids)
        return ids

    adapters.youtube.search, adapters.youtube.videos = search, huge_in_us
    p = await run_to(orch, sample_input, "s2")
    assert sum(1 for r in p.refs if not r.market) >= 4


async def test_unrelated_trending_videos_are_dropped(orch, adapters, sample_input):
    def only_searched(user):
        import re

        ids = re.findall(r"video_id:\s*(\S+)", user)
        return {"items": [{"video_id": v, "relevant": not v.startswith("t")} for v in ids]}

    adapters.llm._s2_relevance = only_searched
    p = await run_to(orch, sample_input, "s2")
    assert not any(r.video_id.startswith("t") for r in p.refs)


async def test_world_failure_keeps_local_results(orch, adapters, sample_input):
    real = adapters.youtube.search

    async def search(keyword, region, lang, since, n):
        if region != "KR":
            raise RuntimeError("막힘")
        return await real(keyword, region, lang, since, n)

    adapters.youtube.search = search
    p = await run_to(orch, sample_input, "s2")
    assert p.status["s2"] == "done" and not any(r.market for r in p.refs)
    assert sum(r.selected for r in p.refs) == 4
    assert any("건너뛰었다" in w for w in p.warnings["s2"])


async def test_markets_can_be_turned_off(orch, sample_input):
    orch.settings.search_markets = ""
    p = await run_to(orch, sample_input, "s2")
    assert p.input.world_keywords == [] and not any(r.market for r in p.refs)
    assert len(p.input.keywords) == 3  # 해외를 찾지 않으면 키워드 3개 그대로
    assert sum(r.selected for r in p.refs) == 4


async def test_without_world_searches_three_keywords(orch, adapters, sample_input):
    orch.settings.search_markets = ""
    seen = []
    real = adapters.youtube.search

    async def spy(keyword, region, lang, since, n):
        seen.append(region)
        return await real(keyword, region, lang, since, n)

    adapters.youtube.search = spy
    await run_to(orch, sample_input, "s2")
    assert seen == ["KR", "KR", "KR"]


async def test_one_market_gives_local_three_searches(orch, adapters, sample_input):
    orch.settings.search_markets = "en:US"
    sample_input.keywords = ["가", "나", "다"]
    seen = []
    real = adapters.youtube.search

    async def spy(keyword, region, lang, since, n):
        seen.append(region)
        return await real(keyword, region, lang, since, n)

    adapters.youtube.search = spy
    await run_to(orch, sample_input, "s2")
    assert seen == ["KR", "KR", "KR", "US"]


def test_markets_setting_ignores_bad_entries():
    from app.config import Settings

    s = Settings(_env_file=None, search_markets=" EN:us, bad ,ja:JP,:KR")
    assert s.markets == [("en", "US"), ("ja", "JP")]


async def test_s1_survives_llm_failure_when_keywords_exist(orch, adapters, sample_input):
    def broken(user):
        raise RuntimeError("한도")

    sample_input.keywords = ["고친 키워드"]
    adapters.llm._s1_keywords = broken
    p = await run_to(orch, sample_input, "s1")
    assert p.status["s1"] == "done" and p.input.keywords == ["고친 키워드"]
    assert any("해외 검색어" in w for w in p.warnings["s1"])


async def test_s1_drops_blank_world_keyword(orch, adapters, sample_input):
    def blank(user):
        return {
            "keywords": ["가", "나", "다"],
            "world": [{"lang": "en", "keyword": " "}, {"lang": "ja", "keyword": "宅トレ"}],
        }

    adapters.llm._s1_keywords = blank
    p = await run_to(orch, sample_input, "s1")
    assert [w.lang for w in p.input.world_keywords] == ["ja"]


async def test_changing_topic_remakes_world_keywords(orch, sample_input):
    p = await run_to(orch, sample_input, "s1")
    assert p.input.world_topic == p.input.topic
    calls = []
    real = orch.adapters.llm._s1_keywords

    def spy(user):
        calls.append(user)
        return real(user)

    orch.adapters.llm._s1_keywords = spy
    await orch.run_step(p.id, "s1")
    assert calls == []  # 같은 주제면 다시 부르지 않는다
    changed = p.input.model_copy(update={"topic": "강아지 산책"})
    await orch.edit(p.id, "input", changed)
    p = await orch.run_step(p.id, "s1")
    assert len(calls) == 1 and p.input.world_topic == "강아지 산책"


async def test_quota_block_warns_once_and_keeps_local(orch, adapters, sample_input):
    from app.quota import QuotaExceeded

    real = adapters.youtube.search

    async def search(keyword, region, lang, since, n):
        if region != "KR":
            raise QuotaExceeded("search")
        return await real(keyword, region, lang, since, n)

    adapters.youtube.search = search
    p = await run_to(orch, sample_input, "s2")
    assert p.status["s2"] == "done"
    assert sum("해외 영상은 찾지 않았어요" in w for w in p.warnings["s2"]) == 1


async def test_chart_videos_reach_the_list_when_relevant(orch, adapters, sample_input):
    p = await run_to(orch, sample_input, "s2")  # 평범한 판정이면
    assert p.status["s2"] == "done"

    real = adapters.youtube.trending

    async def strong_chart(region, category=None):
        out = await real(region, category)
        for v in out:
            v.views *= 100
        return out

    def all_relevant(user):
        import re

        ids = re.findall(r"video_id:\s*(\S+)", user)
        return {"items": [{"video_id": v, "relevant": True, "title_ko": "번역"} for v in ids]}

    adapters.youtube.trending, adapters.llm._s2_relevance = strong_chart, all_relevant
    p = await run_to(orch, sample_input, "s2")
    assert any(r.video_id.startswith("t") for r in p.refs)  # 점수 순으로 들어온다


async def test_old_chart_videos_are_excluded(orch, adapters, sample_input):
    from datetime import UTC, datetime

    real = adapters.youtube.trending

    async def old(region, category=None):
        out = await real(region, category)
        for v in out:
            v.published_at = datetime(2024, 8, 1, tzinfo=UTC)
        return out

    adapters.youtube.trending = old
    p = await run_to(orch, sample_input, "s2")
    assert not any(r.video_id.startswith("t") for r in p.refs)


async def test_chart_drops_are_not_counted_in_warning(orch, adapters, sample_input):
    def no_chart(user):
        import re

        ids = re.findall(r"video_id:\s*(\S+)", user)
        return {"items": [{"video_id": v, "relevant": not v.startswith("t")} for v in ids]}

    adapters.llm._s2_relevance = no_chart
    p = await run_to(orch, sample_input, "s2")
    assert not any("관련이 낮은 후보" in w for w in p.warnings.get("s2", []))


async def test_overseas_titles_are_wrapped_in_prompts(orch, adapters, sample_input):
    seen = {}
    real = adapters.llm.generate_json

    async def spy(task, prompt, user, schema, **kw):
        seen.setdefault(task, user)
        return await real(task, prompt, user, schema, **kw)

    adapters.llm.generate_json = spy
    await run_to(orch, sample_input, "s4")
    for task in ("s2_relevance", "s3_factors", "s4_strategy"):
        assert "<untrusted>" in seen[task]


async def test_market_of_same_language_is_skipped(orch, sample_input):
    orch.settings.search_markets = "ko:KR,en:US"
    p = await run_to(orch, sample_input, "s1")
    assert [w.lang for w in p.input.world_keywords] == ["en"]


def test_choose_limits_one_channel_and_alternates_markets():
    refs = [ref(f"l{i}", channel="same") for i in range(4)]
    refs += [ref("l9"), ref("u1", "US"), ref("u2", "US"), ref("u3", "US"), ref("j1", "JP")]
    chosen = _choose(refs)
    assert len(chosen) == 6
    assert sum(1 for r in chosen if r.channel_id == "same") == 2
    assert {r.video_id for r in chosen if r.market} == {"u1", "j1", "u2"}


def test_choose_fills_past_channel_limit_rather_than_analyse_less():
    refs = [ref(f"l{i}", channel="same") for i in range(5)]
    assert len(_choose(refs)) == 4  # 후보가 좁은 주제에서 분석 근거가 2개로 줄지 않는다


def test_choose_fills_with_local_when_overseas_is_short():
    refs = [ref(f"l{i}") for i in range(5)] + [ref("u1", "US")]
    chosen = _choose(refs)
    assert len(chosen) == 6 and sum(1 for r in chosen if not r.market) == 5


async def test_too_few_matching_videos_are_reported(orch, adapters, sample_input):
    def few(user):
        import re

        ids = re.findall(r"video_id:\s*(\S+)", user)
        return {"items": [{"video_id": v, "relevant": i < 2} for i, v in enumerate(ids)]}

    adapters.llm._s2_relevance = few
    p = await run_to(orch, sample_input, "s2")
    assert sum(r.selected for r in p.refs) == 2
    assert any("2개뿐" in w for w in p.warnings["s2"])


async def test_low_view_videos_go_last_and_warn(orch, adapters, sample_input):
    real = adapters.youtube.videos

    async def small(ids):
        out = await real(ids)
        for v in out:
            v.views = MIN_REF_VIEWS - 1
        return out

    adapters.youtube.videos = small
    p = await run_to(orch, sample_input, "s2")
    assert any("미만 영상" in w for w in p.warnings["s2"])


async def test_translated_copy_of_overseas_title_is_rejected(orch, adapters, sample_input):
    """번역한 베끼기: 원문과 단어가 달라 원문 비교로는 잡히지 않는다."""
    calls = []

    def s4(user):
        from app.adapters.fake import FakeLLM

        calls.append(user)
        s = FakeLLM()._s4_strategy(user)
        if len(calls) == 1:
            s["titles"][0] = "번역된 제목 복사본"
        return s

    def relevance(user):
        import re

        ids = re.findall(r"video_id:\s*(\S+)", user)
        return {
            "items": [
                {"video_id": v, "relevant": True, "title_ko": "번역된 제목 복사본"} for v in ids
            ]
        }

    adapters.llm._s2_relevance, adapters.llm._s4_strategy = relevance, s4
    p = await run_to(orch, sample_input, "s4")
    assert p.status["s4"] == "done" and len(calls) == 2
    assert "너무 비슷하다" in calls[1]
    assert jaccard(title_tokens("번역된 제목 복사본"), title_tokens(p.strategy.titles[0])) < 0.6
