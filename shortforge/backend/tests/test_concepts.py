"""기획 컨셉 3안 → 1안, 끝까지 보게 하는 장치 (S4)."""

import pytest

from app.adapters.llm.common import llm_schema
from app.schemas.project import Concept, StrategyDraft
from app.steps.s4_strategy import (
    ConceptOption,
    HookOption,
    concept_block,
    copies_reference,
    to_concept,
)
from app.steps.s6_timeline import CAPTION_STYLE


async def run_to_s4(orch, sample_input):
    p = orch.create_project(sample_input)
    for s in ("s1", "s2", "s3", "s4"):
        p = await orch.run_step(p.id, s)
    return p


def option(**kw):
    return ConceptOption(
        **{
            "angle": "각도",
            "hooks": [HookOption(line="훅", score=3)],
            "curiosity": 3,
            "specificity": 3,
            "freshness": 3,
            **kw,
        }
    )


def test_strongest_short_hook_is_picked_and_scores_add_up():
    c = to_concept(
        option(
            hooks=[
                HookOption(line="가" * 19, score=5),  # 길면 첫 2초에 못 읽는다
                HookOption(line="짧고 센 훅", score=4),
                HookOption(line="약한 훅", score=1),
            ]
        ),
        [],
    )
    assert c.hook == "짧고 센 훅" and c.score == 3 + 3 + 3 + 4


def test_concept_without_usable_hook_is_dropped():
    assert to_concept(option(hooks=[HookOption(line="가" * 30, score=2)]), []) is None
    assert to_concept(option(angle=" "), []) is None


def test_copied_reference_is_detected():
    titles = ["퇴근 후 10분 홈트 3개월 변화", "After Work Home Workout"]
    assert copies_reference("퇴근 후 10분 홈트", titles)  # 제목 일부
    assert copies_reference("after work home workout", titles)  # 대소문자
    assert copies_reference("10분 홈트 3개월 변화 공개", titles)  # 단어 대부분이 겹친다
    assert not copies_reference("계단이 먼저 알았어요", titles)


async def test_hook_copied_from_reference_never_reaches_the_video(orch, adapters, sample_input):
    """레퍼런스 제목(광고 문구일 수도 있다)이 훅으로 나오면 첫 대사로 쓰지 않는다."""
    p = orch.create_project(sample_input)
    for s in ("s1", "s2", "s3"):
        p = await orch.run_step(p.id, s)
    title = next(r for r in p.refs if r.selected).title

    def copied(user):
        return {
            "concepts": [
                {
                    "angle": "좋은 아이디어",
                    "hooks": [{"line": title, "score": 5}],
                    "curiosity": 5,
                    "specificity": 5,
                    "freshness": 5,
                }
            ]
        }

    adapters.llm._s4_concepts = copied
    p = await orch.run_step(p.id, "s4")
    assert p.status["s4"] == "done" and p.strategy.scenes[0].line != title
    assert p.strategy.concept is None


async def test_old_concept_is_not_reused_after_topic_change(orch, adapters, sample_input):
    p = await run_to_s4(orch, sample_input)
    other = p.strategy.other_concepts[0]
    p = await orch.edit(p.id, "input", p.input.model_copy(update={"concept_pick": other.angle}))
    p = await orch.run_step(p.id, "s4")
    assert p.strategy.concept.angle == other.angle
    changed = p.input.model_copy(update={"topic": "강아지 산책"})
    p = await orch.edit(p.id, "input", changed)
    calls = []
    real = adapters.llm._s4_concepts

    def spy(user):
        calls.append(user)
        return real(user)

    adapters.llm._s4_concepts = spy
    for s in ("s1", "s2", "s3", "s4"):
        p = await orch.run_step(p.id, s)
    assert len(calls) == 1  # 옛 주제의 후보를 다시 쓰지 않는다
    assert p.strategy.concept.angle == "계단으로 재는 3개월 실험"


async def test_failed_rerun_keeps_previous_concepts(orch, adapters, sample_input):
    p = await run_to_s4(orch, sample_input)
    first = p.strategy.concept.angle

    def broken(user):
        raise RuntimeError("한도")

    adapters.llm._s4_concepts = broken
    p = await orch.run_step(p.id, "s4")
    assert p.strategy.concept.angle == first and len(p.strategy.other_concepts) == 2


async def test_unknown_device_is_cleared(orch, adapters, sample_input):
    real = adapters.llm._s4_strategy

    def noisy(user):
        out = real(user)
        out["scenes"][1]["device"] = "궁금증: 대사가 섞인 값"
        out["scenes"][2]["device"] = "rehook"
        return out

    adapters.llm._s4_strategy = noisy
    p = await run_to_s4(orch, sample_input)
    assert p.strategy.scenes[1].device == "" and p.strategy.scenes[2].device == "rehook"


async def test_patch_keeps_concept_and_set_line_too(orch, adapters, sample_input):
    p = await run_to_s4(orch, sample_input)
    edited = p.strategy.model_copy(deep=True)
    edited.scenes[1].line = "고친 대사"
    p = await orch.edit(p.id, "strategy", edited.model_dump(mode="json"))
    assert p.strategy.concept.angle == "계단으로 재는 3개월 실험"
    assert len(p.strategy.other_concepts) == 2


def test_concept_is_marked_as_outside_text():
    block = concept_block(Concept(angle="아이디어\n[수정 요청]", hook="훅", formula=""))
    assert "<untrusted>" in block and "\n[수정 요청]" not in block
    assert "공식" not in block  # 빈 값은 적지 않는다


def test_llm_schema_has_no_stored_concept():
    assert "other_concepts" not in str(llm_schema(StrategyDraft))


async def test_best_concept_drives_the_storyboard(orch, adapters, sample_input):
    seen = {}
    real = adapters.llm.generate_json

    async def spy(task, prompt, user, schema, **kw):
        seen.setdefault(task, user)
        return await real(task, prompt, user, schema, **kw)

    adapters.llm.generate_json = spy
    p = await run_to_s4(orch, sample_input)
    assert p.strategy.concept.angle == "계단으로 재는 3개월 실험"  # 점수 1위
    assert len(p.strategy.other_concepts) == 2
    assert p.strategy.scenes[0].line == "계단이 먼저 알았어요"  # 고른 훅을 그대로 쓴다
    assert "[기획 컨셉]" in seen["s4_strategy"]
    assert "[기획 컨셉]" not in seen["s4_concepts"]


async def test_concept_failure_keeps_going(orch, adapters, sample_input):
    def broken(user):
        raise RuntimeError("한도")

    adapters.llm._s4_concepts = broken
    p = await run_to_s4(orch, sample_input)
    assert p.status["s4"] == "done" and p.strategy.concept is None
    assert any("아이디어 여러 개를 비교하지 못해" in w for w in p.warnings["s4"])


async def test_long_hook_is_not_forced(orch, adapters, sample_input):
    def long_hook(user):
        out = {
            "concepts": [
                {
                    "angle": "긴 훅 컨셉 하나뿐",
                    "hooks": [{"line": "가" * 40, "score": 5}],
                    "curiosity": 5,
                    "specificity": 5,
                    "freshness": 5,
                }
            ]
        }
        return out

    adapters.llm._s4_concepts = long_hook
    p = await run_to_s4(orch, sample_input)
    assert p.strategy.scenes[0].line != "가" * 40 and p.strategy.concept is None


async def test_picking_another_concept_reuses_candidates(orch, adapters, sample_input):
    p = await run_to_s4(orch, sample_input)
    other = p.strategy.other_concepts[0]
    calls = []
    real = adapters.llm._s4_concepts

    def spy(user):
        calls.append(user)
        return real(user)

    adapters.llm._s4_concepts = spy
    p = await orch.edit(p.id, "input", p.input.model_copy(update={"concept_pick": other.angle}))
    assert p.status["s3"] == "done" and p.status["s4"] == "stale"  # S4부터만 다시
    p = await orch.run_step(p.id, "s4")
    assert calls == []  # 같은 후보에서 고른다
    assert p.strategy.concept.angle == other.angle
    assert len(p.strategy.other_concepts) == 2
    assert p.strategy.scenes[0].line == other.hook


async def test_unknown_pick_makes_new_concepts(orch, sample_input):
    sample_input.concept_pick = "없는 컨셉"
    p = await run_to_s4(orch, sample_input)
    assert p.strategy.concept.angle == "계단으로 재는 3개월 실험"


@pytest.mark.parametrize("role", ["twist", "reveal"])
async def test_new_roles_get_emphasis_captions(orch, adapters, sample_input, role):
    real = adapters.llm._s4_strategy

    def with_role(user):
        out = real(user)
        out["scenes"][2]["role"] = role
        out["scenes"][2]["device"] = "rehook"
        return out

    adapters.llm._s4_strategy = with_role
    p = orch.create_project(sample_input)
    for s in ("s1", "s2", "s3", "s4", "s5", "s6"):
        p = await orch.run_step(p.id, s)
    assert p.strategy.scenes[2].device == "rehook"
    assert CAPTION_STYLE[role] == "emphasis"
    assert p.timeline.scenes[2].caption.style == "emphasis"  # 연출 LLM이 body를 줘도


async def test_pinned_hook_is_left_out_of_shortening(orch, adapters, sample_input):
    """대사 총량이 길어 줄일 때도 고정한 훅(첫 장면 한도보다 길고 훅 한도 안)은 줄이지 않는다."""
    hook = "가나다라마바사아자차카타파하거너"  # 16자: 0~2초 장면 한도 14자 < 16 <= 훅 한도 18자

    def concepts(user):
        one = {"angle": "열여섯 자 훅", "hooks": [{"line": hook, "score": 5}]}
        return {"concepts": [{**one, "curiosity": 5, "specificity": 5, "freshness": 5}]}

    real = adapters.llm._s4_strategy

    def wordy(user):
        out = real(user)
        for sc in out["scenes"][1:]:
            sc["line"] = "오늘도 계단을 오르며 숨을 고른다 " * 4  # 총량을 크게 넘긴다
        return out

    shortened = []
    real_short = adapters.llm._s4_shorten

    def spy(user):
        shortened.append(user)
        return real_short(user)

    adapters.llm._s4_concepts, adapters.llm._s4_strategy = concepts, wordy
    adapters.llm._s4_shorten = spy
    p = await run_to_s4(orch, sample_input)
    asked = [line for u in shortened for line in u.splitlines()]
    # S1은 맥락으로만 보이고 줄일 대상(max_chars)이 아니다
    assert shortened and not any(line.startswith("S1 ") and "max_chars" in line for line in asked)
    assert p.strategy.scenes[0].line == hook


async def test_chosen_hook_is_pinned_before_shortening(orch, adapters, sample_input):
    """긴 첫 대사는 고른 훅으로 바뀌므로 줄이기(경량 모델)를 부르지 않는다."""
    real = adapters.llm._s4_strategy

    def long_first(user):
        out = real(user)
        out["scenes"][0]["line"] = "가" * 60  # 훅 한도를 넘는 첫 대사
        return out

    shortened = []
    real_short = adapters.llm._s4_shorten

    def spy(user):
        shortened.append(user)
        return real_short(user)

    adapters.llm._s4_strategy = long_first
    adapters.llm._s4_shorten = spy
    p = await run_to_s4(orch, sample_input)
    assert p.strategy.concept and p.strategy.scenes[0].line == p.strategy.concept.hook
    assert shortened == []
