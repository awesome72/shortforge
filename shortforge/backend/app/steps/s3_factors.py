"""S3 성공 요인: 근거와 신뢰도가 있는 요인만 남긴다 (F-3.1, F-3.2).

썸네일 비전 분석(F-3.3): LLM이 이미지를 볼 수 있으면 선택한 영상의 썸네일 URL을 넘겨
화면 문구·인물·색·구도를 짧게 관찰하게 하고, 그 결과를 `thumbnail` 필드로 요인 근거에 쓴다.
썸네일은 내려받지 않는다(URL만 넘긴다). 실패해도 S3는 실패시키지 않는다.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.llm import load_prompt, wrap_untrusted
from app.orchestrator import StepContext, StepInputError
from app.schemas.project import Factor, Input, Ref

COMMENTS_PER_VIDEO = 100
COMMENTS_IN_PROMPT = 20
MAX_THUMBNAILS = 8  # 한 번의 비전 호출에 넘기는 썸네일 수
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
    "thumbnail",
)
EVIDENCE_FIELD = re.compile("^(" + "|".join(re.escape(f) for f in EVIDENCE_FIELDS) + ")$")


class FactorsOut(BaseModel):
    factors: list[Factor]


class ThumbnailNote(BaseModel):
    video_id: str
    observation: str


class ThumbnailsOut(BaseModel):
    thumbnails: list[ThumbnailNote]


async def describe_thumbnails(ctx: StepContext, refs: list[Ref]) -> dict[str, str]:
    """썸네일 관찰 {video_id: 문장}. 이미지를 볼 수 없는 LLM이거나 실패하면 빈 dict."""
    llm = ctx.adapters.llm
    targets = [r for r in refs if r.thumbnail_url.startswith("https://")][:MAX_THUMBNAILS]
    if not getattr(llm, "supports_images", False) or not targets:
        return {}
    await ctx.progress("thumbnails", 0.0)
    user = "\n".join(f"video_id: {r.video_id}" for r in targets)
    try:
        out = await llm.generate_json(
            "s3_thumbnails",
            load_prompt("s3_thumbnails").text,
            user,
            ThumbnailsOut,
            images=[r.thumbnail_url for r in targets],
        )
    except Exception as e:  # noqa: BLE001 - 썸네일은 보조 근거라 S3를 멈추지 않는다
        ctx.warn(f"썸네일 분석을 건너뛰었다: {e}")
        return {}
    ids = {r.video_id for r in targets}
    return {
        n.video_id: n.observation.strip()
        for n in out.thumbnails
        if n.video_id in ids and n.observation.strip()
    }


async def run(ctx: StepContext) -> list[Factor]:
    inp: Input = ctx.read("input")
    refs: list[Ref] = [r for r in ctx.read("refs") if r.selected]
    if not refs:
        raise StepInputError("선택한 레퍼런스가 없다 — S2에서 1개 이상 선택한다")

    thumbs = await describe_thumbnails(ctx, refs)
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
                    # 썸네일 속 글자는 외부 텍스트라 관찰 결과도 감싼다
                    *(
                        [f"thumbnail: {wrap_untrusted(thumbs[r.video_id])}"]
                        if r.video_id in thumbs
                        else []
                    ),
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
