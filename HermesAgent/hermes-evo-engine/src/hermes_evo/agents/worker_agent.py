"""Worker Agent — 无状态任务执行包装器.

管理单次任务的 HermesReActAgent 生命周期：
创建 Agent → 执行任务 → 收集结果 → 返回
"""

from __future__ import annotations

import logging

from hermes_evo.agents.hermes_react_agent import HermesReActAgent
from hermes_evo.core.dual_engine import DualEngineLearner
from hermes_evo.core.skill_manager import SkillManager
from hermes_evo.models.agent import AgentTask, ExecutionRecord

logger = logging.getLogger(__name__)


class WorkerAgent:
    """无状态 Worker — 每次任务创建新的 HermesReActAgent 实例."""

    def __init__(
        self,
        skill_manager: SkillManager,
        dual_engine: DualEngineLearner,
        model_config: dict | None = None,
        available_tools: list[str] | None = None,
    ) -> None:
        self.skill_manager = skill_manager
        self.dual_engine = dual_engine
        self._model_config = model_config or {}
        self._available_tools = available_tools or []

    async def execute(self, task: AgentTask) -> ExecutionRecord:
        """执行单个任务.

        1. 创建 HermesReActAgent 实例
        2. 执行任务
        3. 返回执行记录
        """
        agent = HermesReActAgent(
            name=f"worker-{task.task_id[:8]}",
            skill_manager=self.skill_manager,
            dual_engine=self.dual_engine,
            available_tools=self._available_tools,
            model_config=self._model_config,
            max_iters=task.max_iters or 20,
        )

        logger.info(
            "Worker executing task: id=%s instruction='%s'",
            task.task_id,
            task.instruction[:80],
        )

        record = await agent.execute(
            instruction=task.instruction,
            context=task.context,
        )
        # 覆盖 task_id 以匹配原始请求
        record.task_id = task.task_id

        logger.info(
            "Worker completed task: id=%s success=%s",
            task.task_id,
            record.success,
        )
        return record
