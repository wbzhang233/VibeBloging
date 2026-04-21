"""请求/响应 Schema — FastAPI 序列化模型."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ── Skills ─────────────────────────────────────────────────────────────


class SkillCreateBody(BaseModel):
    name: str
    description: str
    content: str
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    fallback_for_toolsets: list[str] = Field(default_factory=list)
    requires_tools: list[str] = Field(default_factory=list)
    requires_toolsets: list[str] = Field(default_factory=list)
    fallback_for_tools: list[str] = Field(default_factory=list)


class SkillPatchBody(BaseModel):
    old_string: str
    new_string: str
    reason: str = ""


class SkillResponse(BaseModel):
    id: str
    name: str
    description: str
    content: str
    category: str = ""
    version: int
    status: str
    safety_level: str
    created_by: str
    tags: list[str]
    use_count: int
    created_at: datetime
    updated_at: datetime
    patch_count: int = 0


class SkillListResponse(BaseModel):
    total: int
    skills: list[SkillResponse]


# ── Agents ─────────────────────────────────────────────────────────────


class AgentExecuteBody(BaseModel):
    instruction: str
    context: dict = Field(default_factory=dict)
    max_iters: int | None = None


class AgentExecuteResponse(BaseModel):
    task_id: str
    status: str = "submitted"


class TaskResultResponse(BaseModel):
    task_id: str
    agent_id: str
    success: bool
    result: str
    tool_call_count: int
    skills_created: list[str]
    skills_patched: list[str]
    started_at: datetime
    completed_at: datetime | None


class PoolStatusResponse(BaseModel):
    pool_size: int
    active_tasks: int
    total_submitted: int
    total_completed: int
    agents: list[dict]


# ── Review ─────────────────────────────────────────────────────────────


class ReviewTriggerBody(BaseModel):
    agent_id: str
    conversation_history: list[dict] = Field(default_factory=list)


class ReviewResponse(BaseModel):
    review_id: str
    timestamp: datetime
    candidates_count: int
    nothing_to_save: bool
    reasoning: str


class ReviewListResponse(BaseModel):
    total: int
    reviews: list[ReviewResponse]


# ── Metrics ────────────────────────────────────────────────────────────


class MetricsResponse(BaseModel):
    total_skills: int
    skills_by_status: dict[str, int]
    skills_by_safety: dict[str, int]
    skills_by_creator: dict[str, int]
    pool_info: dict
