"""依赖注入 — FastAPI Depends 提供核心服务实例."""

from __future__ import annotations

from hermes_evo.agents.agent_pool import AgentPool
from hermes_evo.core.dual_engine import DualEngineLearner
from hermes_evo.core.review_agent import ReviewAgent
from hermes_evo.core.skill_manager import SkillManager

# 全局服务实例（在 app lifespan 中初始化）
_skill_manager: SkillManager | None = None
_dual_engine: DualEngineLearner | None = None
_agent_pool: AgentPool | None = None
_review_agent: ReviewAgent | None = None


def init_services(
    skill_manager: SkillManager,
    dual_engine: DualEngineLearner,
    agent_pool: AgentPool,
    review_agent: ReviewAgent,
) -> None:
    """在 app lifespan 中调用，注册全局服务."""
    global _skill_manager, _dual_engine, _agent_pool, _review_agent  # noqa: PLW0603
    _skill_manager = skill_manager
    _dual_engine = dual_engine
    _agent_pool = agent_pool
    _review_agent = review_agent


def get_skill_manager() -> SkillManager:
    assert _skill_manager is not None, "SkillManager not initialized"
    return _skill_manager


def get_dual_engine() -> DualEngineLearner:
    assert _dual_engine is not None, "DualEngineLearner not initialized"
    return _dual_engine


def get_agent_pool() -> AgentPool:
    assert _agent_pool is not None, "AgentPool not initialized"
    return _agent_pool


def get_review_agent() -> ReviewAgent:
    assert _review_agent is not None, "ReviewAgent not initialized"
    return _review_agent
