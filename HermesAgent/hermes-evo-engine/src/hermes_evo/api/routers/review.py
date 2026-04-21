"""/review — 后台巡检触发与历史查询."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from hermes_evo.api.dependencies import get_dual_engine
from hermes_evo.api.schemas import ReviewResponse, ReviewTriggerBody
from hermes_evo.core.dual_engine import DualEngineLearner

router = APIRouter(prefix="/review", tags=["review"])

# 内存中保存巡检历史（生产环境应持久化到数据库）
_review_history: list[dict] = []


@router.post("/trigger", response_model=ReviewResponse)
async def trigger_review(
    body: ReviewTriggerBody,
    engine: DualEngineLearner = Depends(get_dual_engine),
):
    """手动触发后台巡检（忽略阈值）."""
    result = await engine.force_review(
        agent_id=body.agent_id,
        conversation_history=body.conversation_history,
    )

    response = ReviewResponse(
        review_id=result.review_id,
        timestamp=result.timestamp,
        candidates_count=len(result.candidates),
        nothing_to_save=result.nothing_to_save,
        reasoning=result.reasoning,
    )

    _review_history.append(response.model_dump(mode="json"))
    return response


@router.get("/history")
async def list_reviews(limit: int = 20):
    """获取巡检历史."""
    return {
        "total": len(_review_history),
        "reviews": _review_history[-limit:],
    }
