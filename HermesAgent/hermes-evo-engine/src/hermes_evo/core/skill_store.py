"""Skill 持久化层 — 双写策略: TDSQL (MySQL) + 文件系统."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import select, update

from hermes_evo.config import settings
from hermes_evo.infra.database import SkillRecord, async_session_factory
from hermes_evo.models.skill import SkillMetadata, SkillPatch, SkillStatus

logger = logging.getLogger(__name__)


class SkillStore:
    """Skill 存储层: TDSQL (MySQL) 元数据查询 + 文件系统人类可读备份."""

    def __init__(self, base_path: str | None = None) -> None:
        self._base = Path(base_path or settings.skill_store_path)
        self._base.mkdir(parents=True, exist_ok=True)

    # ── 写入 ───────────────────────────────────────────────────────────

    async def save(self, skill: SkillMetadata) -> None:
        """保存 Skill 到数据库 + 文件系统."""
        async with async_session_factory() as session:
            record = SkillRecord(
                id=skill.id,
                name=skill.name,
                description=skill.description,
                content=skill.content,
                category=skill.category,
                version=skill.version,
                status=skill.status.value,
                created_at=skill.created_at,
                updated_at=skill.updated_at,
                created_by=skill.created_by,
                tags=skill.tags,
                fallback_for_toolsets=skill.fallback_for_toolsets,
                requires_tools=skill.requires_tools,
                requires_toolsets=skill.requires_toolsets,
                fallback_for_tools=skill.fallback_for_tools,
                safety_level=skill.safety_level,
                use_count=skill.use_count,
                patch_history=[p.model_dump(mode="json") for p in skill.patch_history],
            )
            session.add(record)
            await session.commit()
        self._write_file(skill)

    async def update(self, skill: SkillMetadata) -> None:
        """更新已有 Skill."""
        async with async_session_factory() as session:
            await session.execute(
                update(SkillRecord)
                .where(SkillRecord.id == skill.id)
                .values(
                    name=skill.name,
                    description=skill.description,
                    content=skill.content,
                    category=skill.category,
                    version=skill.version,
                    status=skill.status.value,
                    updated_at=datetime.now(timezone.utc),
                    tags=skill.tags,
                    fallback_for_toolsets=skill.fallback_for_toolsets,
                    requires_tools=skill.requires_tools,
                    requires_toolsets=skill.requires_toolsets,
                    fallback_for_tools=skill.fallback_for_tools,
                    safety_level=skill.safety_level,
                    use_count=skill.use_count,
                    patch_history=[
                        p.model_dump(mode="json") for p in skill.patch_history
                    ],
                )
            )
            await session.commit()
        self._write_file(skill)

    # ── 读取 ───────────────────────────────────────────────────────────

    async def get(self, skill_id: str) -> SkillMetadata | None:
        """按 ID 获取 Skill."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(SkillRecord).where(SkillRecord.id == skill_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            return self._record_to_metadata(record)

    async def get_by_name(self, name: str) -> SkillMetadata | None:
        """按名称获取 Skill."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(SkillRecord).where(SkillRecord.name == name)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            return self._record_to_metadata(record)

    async def list_all(
        self,
        status: str | None = None,
        tag: str | None = None,
        safety_level: str | None = None,
        query: str | None = None,
    ) -> list[SkillMetadata]:
        """列出所有 Skill，支持过滤."""
        async with async_session_factory() as session:
            stmt = select(SkillRecord)
            if status:
                stmt = stmt.where(SkillRecord.status == status)
            if safety_level:
                stmt = stmt.where(SkillRecord.safety_level == safety_level)
            if query:
                stmt = stmt.where(SkillRecord.name.ilike(f"%{query}%"))
            result = await session.execute(stmt.order_by(SkillRecord.updated_at.desc()))
            records = result.scalars().all()

        skills = [self._record_to_metadata(r) for r in records]
        # 按 tag 过滤（JSON contains 在 Python 侧处理，更简单）
        if tag:
            skills = [s for s in skills if tag in s.tags]
        return skills

    # ── 文件系统 ───────────────────────────────────────────────────────

    def _write_file(self, skill: SkillMetadata) -> None:
        """将 Skill 写为 YAML frontmatter + Markdown 格式."""
        frontmatter = {
            "name": skill.name,
            "description": skill.description,
            "category": skill.category,
            "version": skill.version,
            "status": skill.status.value,
            "tags": skill.tags,
            "fallback_for_toolsets": skill.fallback_for_toolsets,
            "requires_tools": skill.requires_tools,
            "requires_toolsets": skill.requires_toolsets,
            "fallback_for_tools": skill.fallback_for_tools,
            "safety_level": skill.safety_level,
            "created_by": skill.created_by,
        }
        content_lines = [
            "---",
            yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip(),
            "---",
            "",
            f"# {skill.name}",
            "",
            skill.content,
        ]
        if skill.patch_history:
            content_lines.extend(["", "## Patch History", ""])
            for patch in skill.patch_history:
                ts = patch.timestamp.strftime("%Y-%m-%d %H:%M")
                content_lines.append(
                    f"- {ts} v{skill.version} ({patch.applied_by}): {patch.reason or 'no reason'}"
                )

        filepath = self._base / f"{skill.id}.md"
        filepath.write_text("\n".join(content_lines), encoding="utf-8")
        logger.debug("Skill file written: %s", filepath)

    # ── 工具方法 ───────────────────────────────────────────────────────

    @staticmethod
    def _record_to_metadata(record: SkillRecord) -> SkillMetadata:
        """ORM 记录 -> Pydantic 模型."""
        return SkillMetadata(
            id=record.id,
            name=record.name,
            description=record.description,
            content=record.content,
            category=getattr(record, "category", ""),
            version=record.version,
            status=SkillStatus(record.status),
            created_at=record.created_at,
            updated_at=record.updated_at,
            created_by=record.created_by,
            tags=record.tags or [],
            fallback_for_toolsets=record.fallback_for_toolsets or [],
            requires_tools=record.requires_tools or [],
            requires_toolsets=getattr(record, "requires_toolsets", None) or [],
            fallback_for_tools=getattr(record, "fallback_for_tools", None) or [],
            safety_level=record.safety_level,
            use_count=record.use_count,
            patch_history=[SkillPatch(**p) for p in (record.patch_history or [])],
        )
