"""Agent 任务与状态数据模型."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentTask(BaseModel):
    """提交给 Agent 执行的任务."""

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    instruction: str
    context: dict = Field(default_factory=dict)
    max_iters: int | None = None  # None = 使用全局默认


class AgentStatus(BaseModel):
    """Agent 实例的实时状态."""

    agent_id: str
    state: str = "idle"  # idle | executing | reviewing
    current_task_id: str | None = None
    iters_since_skill: int = 0
    total_tasks_completed: int = 0


class ExecutionRecord(BaseModel):
    """任务执行完成后的记录."""

    task_id: str
    agent_id: str
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    completed_at: datetime | None = None
    tool_calls: list[dict] = Field(default_factory=list)
    skills_created: list[str] = Field(default_factory=list)
    skills_patched: list[str] = Field(default_factory=list)
    result: str = ""
    success: bool = False
