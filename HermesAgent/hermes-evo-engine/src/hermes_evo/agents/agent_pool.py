"""Agent 池管理器 — 并发任务执行与状态追踪."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from hermes_evo.agents.worker_agent import WorkerAgent
from hermes_evo.config import settings
from hermes_evo.core.dual_engine import DualEngineLearner
from hermes_evo.core.skill_manager import SkillManager
from hermes_evo.models.agent import AgentStatus, AgentTask, ExecutionRecord

logger = logging.getLogger(__name__)


class AgentPool:
    """Agent 并发池.

    功能：
    - 提交任务到异步队列
    - 限制并发执行数（Semaphore）
    - 追踪任务结果
    - 查询池状态
    """

    def __init__(
        self,
        skill_manager: SkillManager,
        dual_engine: DualEngineLearner,
        pool_size: int | None = None,
        model_config: dict | None = None,
    ) -> None:
        self.skill_manager = skill_manager
        self.dual_engine = dual_engine
        self._pool_size = pool_size or settings.agent_pool_size
        self._semaphore = asyncio.Semaphore(self._pool_size)
        self._model_config = model_config or {}

        # 任务追踪
        self._tasks: dict[str, asyncio.Task] = {}
        self._results: dict[str, ExecutionRecord] = {}
        self._active_agents: dict[str, AgentStatus] = {}

    async def submit_task(self, task: AgentTask) -> str:
        """提交任务到池中异步执行.

        Returns:
            task_id
        """
        if not task.task_id:
            task.task_id = str(uuid4())

        agent_id = f"pool-worker-{task.task_id[:8]}"
        self._active_agents[agent_id] = AgentStatus(
            agent_id=agent_id,
            state="pending",
            current_task_id=task.task_id,
        )

        async_task = asyncio.create_task(
            self._execute_with_semaphore(task, agent_id)
        )
        self._tasks[task.task_id] = async_task

        logger.info(
            "Task submitted: id=%s pool_active=%d/%d",
            task.task_id,
            self._pool_size - self._semaphore._value,
            self._pool_size,
        )
        return task.task_id

    async def _execute_with_semaphore(
        self,
        task: AgentTask,
        agent_id: str,
    ) -> None:
        """带信号量限制的任务执行."""
        async with self._semaphore:
            self._active_agents[agent_id].state = "executing"
            worker = WorkerAgent(
                skill_manager=self.skill_manager,
                dual_engine=self.dual_engine,
                model_config=self._model_config,
            )
            try:
                record = await worker.execute(task)
                self._results[task.task_id] = record
                self._active_agents[agent_id].state = "idle"
                self._active_agents[agent_id].total_tasks_completed += 1
            except Exception as e:
                logger.error("Pool task failed: %s - %s", task.task_id, e)
                self._results[task.task_id] = ExecutionRecord(
                    task_id=task.task_id,
                    agent_id=agent_id,
                    result=f"Error: {e}",
                    success=False,
                )
                self._active_agents[agent_id].state = "error"

    def get_task_result(self, task_id: str) -> ExecutionRecord | None:
        """获取已完成任务的结果."""
        return self._results.get(task_id)

    def get_status(self) -> list[AgentStatus]:
        """获取所有 Agent 状态."""
        return list(self._active_agents.values())

    def get_pool_info(self) -> dict:
        """获取池概况."""
        return {
            "pool_size": self._pool_size,
            "active_tasks": self._pool_size - self._semaphore._value,
            "total_submitted": len(self._tasks),
            "total_completed": len(self._results),
            "agents": len(self._active_agents),
        }
