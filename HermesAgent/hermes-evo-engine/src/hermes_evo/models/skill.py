"""Skill 数据模型 — 自进化系统的核心数据结构."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class SkillStatus(str, Enum):
    """Skill 生命周期状态."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    CAUTION = "caution"
    DANGEROUS = "dangerous"


class SkillPatch(BaseModel):
    """一次热补丁记录."""

    patch_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    old_string: str
    new_string: str
    reason: str = ""
    applied_by: str = "agent"  # "proactive" | "background_review" | "manual"


class SkillMetadata(BaseModel):
    """Skill 完整元数据."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str
    content: str  # Skill 正文（步骤、指令、代码片段）
    category: str = ""  # Skill 分类（可选）
    version: int = 1
    status: SkillStatus = SkillStatus.ACTIVE
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    created_by: str = "manual"  # "proactive" | "background_review" | "manual"
    tags: list[str] = Field(default_factory=list)

    # 条件激活（四条规则，对齐 prompt_builder.py _skill_should_show()）
    fallback_for_toolsets: list[str] = Field(default_factory=list)
    requires_tools: list[str] = Field(default_factory=list)
    requires_toolsets: list[str] = Field(default_factory=list)
    fallback_for_tools: list[str] = Field(default_factory=list)

    # 安全等级
    safety_level: str = "safe"  # safe | low | medium | high | critical

    # 使用统计
    use_count: int = 0

    # 补丁历史
    patch_history: list[SkillPatch] = Field(default_factory=list)


# ── 请求模型 ───────────────────────────────────────────────────────────


class SkillCreateRequest(BaseModel):
    """创建 Skill 的请求体."""

    name: str
    description: str
    content: str
    category: str = ""  # Skill 分类（可选）
    tags: list[str] = Field(default_factory=list)
    fallback_for_toolsets: list[str] = Field(default_factory=list)
    requires_tools: list[str] = Field(default_factory=list)
    requires_toolsets: list[str] = Field(default_factory=list)
    fallback_for_tools: list[str] = Field(default_factory=list)


class SkillPatchRequest(BaseModel):
    """热补丁请求体."""

    old_string: str
    new_string: str
    reason: str = ""
