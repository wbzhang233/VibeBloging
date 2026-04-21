"""Review Agent 数据模型 — 后台巡检的输入输出."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class LearningCandidate(BaseModel):
    """审查 Agent 识别出的一个值得保存的经验."""

    name: str
    description: str
    content: str
    source_task_ids: list[str] = Field(default_factory=list)
    evidence: str  # 为什么值得保存
    action: str  # "create" | "update"
    target_skill_id: str | None = None  # action="update" 时指定


class ReviewResult(BaseModel):
    """一次后台巡检的完整结果."""

    review_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    conversation_window: int = 0  # 审查了多少轮迭代
    candidates: list[LearningCandidate] = Field(default_factory=list)
    nothing_to_save: bool = False
    reasoning: str = ""  # 审查 Agent 的完整推理
