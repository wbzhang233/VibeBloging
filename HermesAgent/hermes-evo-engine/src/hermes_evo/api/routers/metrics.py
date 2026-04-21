"""/metrics — 系统指标."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends

from hermes_evo.agents.agent_pool import AgentPool
from hermes_evo.api.dependencies import get_agent_pool, get_skill_manager
from hermes_evo.api.schemas import MetricsResponse
from hermes_evo.core.skill_manager import SkillManager

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
async def get_metrics(
    sm: SkillManager = Depends(get_skill_manager),
    pool: AgentPool = Depends(get_agent_pool),
):
    """系统全局指标."""
    all_skills = await sm.list_skills()

    status_counter: Counter = Counter()
    safety_counter: Counter = Counter()
    creator_counter: Counter = Counter()
    for skill in all_skills:
        status_counter[skill.status.value] += 1
        safety_counter[skill.safety_level] += 1
        creator_counter[skill.created_by] += 1

    return MetricsResponse(
        total_skills=len(all_skills),
        skills_by_status=dict(status_counter),
        skills_by_safety=dict(safety_counter),
        skills_by_creator=dict(creator_counter),
        pool_info=pool.get_pool_info(),
    )
