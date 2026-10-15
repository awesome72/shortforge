"""S3 성공 요인: 근거와 신뢰도가 있는 요인만 남긴다 (F-3.1, F-3.2)."""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.llm import load_prompt, wrap_untrusted
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Factor, Input, Ref

COMMENTS_PER_VIDEO = 100
COMMENTS_IN_PROMPT = 20
ALWAYS_ESTIMATED = {"hook", "visual"}  # 메타데이터로 직접 확인할 수 없는 요인
# 근거로 인정하는 필드 = 아래 run()이 프롬프트에 실제로 넣는 필드. 둘은 함께 바꾼다.
# 시청 지속률·유입 경로처럼 API가 주지 않는 데이터는 근거가 될 수 없다.
EVIDENCE_FIELDS = (
    "snippet.title",
    "snippet.publishedAt",
    "contentDetails.duration",
    "statistics.viewCount",
    "statistics.likeCount",
    "channel.subscriberCount",
    "commentThreads",
)
EVIDENCE_FIELD = re.compile("^(" + "|".join(re.escape(f) for f in EVIDENCE_FIELDS) + ")$")


class FactorsOut(BaseModel):
    factors: list[Factor]


async def run(ctx: StepContext) -> list[Factor]:
    inp: Input = ctx.read("input")
    refs: list[Ref] = [r for r in ctx.read("refs") if r.selected]
    if not refs:
        raise StepInputError("선택한 레퍼런스가 없다 — S2에서 1개 이상 선택한다")

    blocks = []
    for i, r in enumerate(refs):
        await ctx.progress(f"comments:{r.video_id}", i / len(refs))
        comments = await ctx.adapters.youtube.top_comments(r.video_id, COMMENTS_PER_VIDEO)
        blocks.append(
            "\n".join(
                [
                    f"video_id: {r.video_id}",
                    f"snippet.title: {wrap_untrusted(r.title)}",
                    f"snippet.publishedAt: {r.published_at.isoformat()}",
                    f"contentDetails.duration: {r.duration_sec}초",
                    f"statistics.viewCount: {r.views}",
                    f"statistics.likeCount: {r.likes} (좋아요율 {r.like_rate:.2%})",
                    f"channel.subscriberCount: {'비공개' if r.subs is None else r.subs}",
                    "commentThreads: "
                    + " | ".join(wrap_untrusted(c) for c in comments[:COMMENTS_IN_PROMPT]),
                ]
            )
        )
    user = f"topic: {inp.topic}\naudience: {inp.audience}\n\n" + "\n\n".join(blocks)

    prompt = load_prompt("s3_factors")
    out = await ctx.adapters.llm.generate_json("s3_factors", prompt.text, user, FactorsOut)
    return _enforce_evidence(ctx, out.factors, {r.video_id for r in refs})


def _enforce_evidence(ctx: StepContext, factors: list[Factor], ids: set[str]) -> list[Factor]:
    """선택한 영상·허용 필드를 가리키지 않는 근거는 지우고, 근거가 없어진 요인은 버린다."""
    kept: list[Factor] = []
    dropped = 0
    for f in factors:
        evidence = [
            e
            for e in f.evidence
            if e.partition(":")[0] in ids and EVIDENCE_FIELD.match(e.partition(":")[2])
        ]
        if not evidence:
            dropped += 1
            continue
        confidence = f.confidence
        if f.name in ALWAYS_ESTIMATED and confidence == "confirmed":
            confidence = "estimated"
            ctx.warn(f"'{f.name}' 요인은 메타데이터로 확인할 수 없어 '추정'으로 낮췄다")
        kept.append(f.model_copy(update={"evidence": evidence, "confidence": confidence}))
    if dropped:
        ctx.warn(f"근거가 없는 요인 {dropped}개를 버렸다")
    if not kept:
        raise StepInputError("근거가 있는 성공 요인이 하나도 없다 — 레퍼런스를 바꿔 본다")
    return kept
