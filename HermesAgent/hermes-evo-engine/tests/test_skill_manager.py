"""Skill Manager 核心逻辑测试.

注：使用内存版 SkillStore 替代 TDSQL (MySQL)。
"""

from __future__ import annotations

import pytest

from hermes_evo.core.skill_manager import (
    AmbiguousPatchError,
    PatchTargetNotFoundError,
    SkillManager,
    SkillNotFoundError,
)
from hermes_evo.models.skill import (
    SkillCreateRequest,
    SkillMetadata,
    SkillPatchRequest,
    SkillStatus,
)


class InMemorySkillStore:
    """内存版 SkillStore，用于单元测试."""

    def __init__(self):
        self._skills: dict[str, SkillMetadata] = {}

    async def save(self, skill: SkillMetadata) -> None:
        self._skills[skill.id] = skill

    async def update(self, skill: SkillMetadata) -> None:
        self._skills[skill.id] = skill

    async def get(self, skill_id: str) -> SkillMetadata | None:
        return self._skills.get(skill_id)

    async def get_by_name(self, name: str) -> SkillMetadata | None:
        for skill in self._skills.values():
            if skill.name == name:
                return skill
        return None

    async def list_all(self, status=None, tag=None, safety_level=None, query=None):
        results = list(self._skills.values())
        if status:
            results = [s for s in results if s.status.value == status]
        if tag:
            results = [s for s in results if tag in s.tags]
        if safety_level:
            results = [s for s in results if s.safety_level == safety_level]
        if query:
            results = [s for s in results if query.lower() in s.name.lower()]
        return results

    def _write_file(self, skill):
        pass  # 测试中不写文件


class TestSkillManager:
    """SkillManager 单元测试."""

    @pytest.fixture
    def manager(self):
        store = InMemorySkillStore()
        return SkillManager(store=store)

    @pytest.mark.asyncio
    async def test_create_skill(self, manager: SkillManager):
        """创建 Skill 并验证元数据."""
        skill = await manager.create_skill(
            SkillCreateRequest(
                name="test-skill",
                description="Test description",
                content="Step 1: Do A\nStep 2: Do B",
                tags=["test"],
            ),
            created_by="test",
        )
        assert skill.name == "test-skill"
        assert skill.version == 1
        assert skill.status == SkillStatus.ACTIVE
        assert skill.safety_level == "safe"
        assert skill.created_by == "test"

    @pytest.mark.asyncio
    async def test_create_duplicate_returns_existing(self, manager: SkillManager):
        """重复名称的 Skill 返回已有实例."""
        skill1 = await manager.create_skill(
            SkillCreateRequest(name="dup", description="first", content="first"),
        )
        skill2 = await manager.create_skill(
            SkillCreateRequest(name="dup", description="second", content="second"),
        )
        assert skill1.id == skill2.id

    @pytest.mark.asyncio
    async def test_create_dangerous_skill(self, manager: SkillManager):
        """包含危险内容的 Skill 自动标记为 DANGEROUS."""
        skill = await manager.create_skill(
            SkillCreateRequest(
                name="danger",
                description="Dangerous",
                content="Run eval(user_input) to process",
            ),
        )
        assert skill.safety_level == "critical"
        assert skill.status == SkillStatus.DANGEROUS

    @pytest.mark.asyncio
    async def test_hot_patch(self, manager: SkillManager):
        """热补丁：替换内容并递增版本."""
        skill = await manager.create_skill(
            SkillCreateRequest(
                name="patchable",
                description="Patchable skill",
                content="Use https://old-api.example.com/v1 to fetch data",
            ),
        )
        patched = await manager.patch_skill(
            skill.id,
            SkillPatchRequest(
                old_string="https://old-api.example.com/v1",
                new_string="https://new-api.example.com/v2",
                reason="API URL changed",
            ),
        )
        assert patched.version == 2
        assert "new-api.example.com/v2" in patched.content
        assert "old-api.example.com/v1" not in patched.content
        assert len(patched.patch_history) == 1
        assert patched.patch_history[0].reason == "API URL changed"

    @pytest.mark.asyncio
    async def test_patch_not_found(self, manager: SkillManager):
        """补丁目标字符串不存在时抛异常."""
        skill = await manager.create_skill(
            SkillCreateRequest(name="s", description="d", content="original content"),
        )
        with pytest.raises(PatchTargetNotFoundError):
            await manager.patch_skill(
                skill.id,
                SkillPatchRequest(old_string="nonexistent", new_string="new"),
            )

    @pytest.mark.asyncio
    async def test_patch_ambiguous(self, manager: SkillManager):
        """补丁目标出现多次时抛异常."""
        skill = await manager.create_skill(
            SkillCreateRequest(
                name="ambig",
                description="d",
                content="foo bar foo baz foo",
            ),
        )
        with pytest.raises(AmbiguousPatchError):
            await manager.patch_skill(
                skill.id,
                SkillPatchRequest(old_string="foo", new_string="qux"),
            )

    @pytest.mark.asyncio
    async def test_deprecate_skill(self, manager: SkillManager):
        """软删除标记为 DEPRECATED."""
        skill = await manager.create_skill(
            SkillCreateRequest(name="dep", description="d", content="c"),
        )
        deprecated = await manager.deprecate_skill(skill.id)
        assert deprecated.status == SkillStatus.DEPRECATED

    @pytest.mark.asyncio
    async def test_get_nonexistent_raises(self, manager: SkillManager):
        """获取不存在的 Skill 抛异常."""
        with pytest.raises(SkillNotFoundError):
            await manager.get_skill("nonexistent-id")

    @pytest.mark.asyncio
    async def test_list_with_filters(self, manager: SkillManager):
        """过滤列表."""
        await manager.create_skill(
            SkillCreateRequest(name="a", description="d", content="c", tags=["python"]),
        )
        await manager.create_skill(
            SkillCreateRequest(name="b", description="d", content="c", tags=["rust"]),
        )
        result = await manager.list_skills(tag="python")
        assert len(result) == 1
        assert result[0].name == "a"

    @pytest.mark.asyncio
    async def test_patch_preserves_context(self, manager: SkillManager):
        """热补丁保留上下文（其他部分不变）."""
        original = "Line 1: Setup\nLine 2: Use https://old.com\nLine 3: Verify"
        skill = await manager.create_skill(
            SkillCreateRequest(name="ctx", description="d", content=original),
        )
        patched = await manager.patch_skill(
            skill.id,
            SkillPatchRequest(
                old_string="https://old.com",
                new_string="https://new.com",
            ),
        )
        assert "Line 1: Setup" in patched.content
        assert "Line 3: Verify" in patched.content
        assert "https://new.com" in patched.content
