"""Skill Manager — CRUD + 热补丁 + 生命周期状态机.

对齐 HermesAgent 源码 tools/skills_tool.py：

六种操作 (actions):
  1. create  — 创建新 Skill
  2. edit    — 全量替换 Skill 内容
  3. patch   — 热补丁修复（精准定位 + fuzzy_find_and_replace 兜底）
  4. delete  — 软删除（标记为 DEPRECATED）
  5. write_file   — 写入 Skill 附属文件
  6. remove_file  — 删除 Skill 附属文件

热补丁设计：
  - 验证 old_string 恰好出现 1 次
  - 就地替换 → 版本号+1 → 重新安全扫描 → 追加补丁历史
  - 不中断当前任务，保留上下文，可追溯
  - 注: 源码中使用 fuzzy_find_and_replace 作为 exact match 失败时的兜底

原子写入模式:
  - 使用 tempfile + os.replace 确保文件写入的原子性
  - 避免写入中断导致的文件损坏

Frontmatter 校验:
  - SKILL.md 必须包含 name 和 description 字段

大小限制:
  - SKILL.md 正文上限 100K 字符
  - 附属文件上限 1 MiB
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from hermes_evo.core.conditional_activation import ConditionalActivator
from hermes_evo.core.safety_scanner import (
    MAX_SKILL_FILE_SIZE,
    MAX_SKILL_MD_CHARS,
    SafetyScanner,
)
from hermes_evo.core.skill_store import SkillStore
from hermes_evo.models.skill import (
    SkillCreateRequest,
    SkillMetadata,
    SkillPatch,
    SkillPatchRequest,
    SkillStatus,
)

logger = logging.getLogger(__name__)


class SkillNotFoundError(Exception):
    """Skill 不存在."""


class PatchTargetNotFoundError(Exception):
    """补丁目标字符串不存在."""


class AmbiguousPatchError(Exception):
    """补丁目标字符串出现多次，无法精准定位."""


class FrontmatterValidationError(Exception):
    """SKILL.md 缺少必需的 frontmatter 字段."""


class SizeLimitExceededError(Exception):
    """内容超过大小限制."""


class SkillManager:
    """Skill 生命周期管理器.

    对齐 HermesAgent 源码 tools/skills_tool.py，支持六种操作。

    职责：
    1. 六种操作: create, edit, patch, delete, write_file, remove_file
    2. 热补丁（hot-patch）+ fuzzy matching 兜底
    3. 条件激活过滤
    4. 安全扫描集成
    5. 使用统计
    6. Frontmatter 校验
    7. 大小限制检查
    8. 原子写入（tempfile + os.replace）
    """

    def __init__(
        self,
        store: SkillStore | None = None,
        scanner: SafetyScanner | None = None,
        activator: ConditionalActivator | None = None,
        skill_store_path: str = "./skill_store",
    ) -> None:
        self.store = store or SkillStore()
        self.scanner = scanner or SafetyScanner()
        self.activator = activator or ConditionalActivator()
        self._skill_store_path = Path(skill_store_path)

    # ── 创建 ───────────────────────────────────────────────────────────

    async def create_skill(
        self,
        request: SkillCreateRequest,
        created_by: str = "manual",
    ) -> SkillMetadata:
        """创建新 Skill.

        流程:
        1. Frontmatter 校验（name + description 必须）
        2. 大小限制检查（SKILL.md ≤ 100K 字符）
        3. 名称去重
        4. 安全扫描
        5. 持久化
        """
        # Frontmatter 校验
        if not request.name or not request.name.strip():
            raise FrontmatterValidationError("Skill 'name' is required in frontmatter")
        if not request.description or not request.description.strip():
            raise FrontmatterValidationError("Skill 'description' is required in frontmatter")

        # 大小限制检查
        if len(request.content) > MAX_SKILL_MD_CHARS:
            raise SizeLimitExceededError(
                f"SKILL.md content exceeds {MAX_SKILL_MD_CHARS:,} character limit "
                f"(actual: {len(request.content):,})"
            )

        # 去重检查
        existing = await self.store.get_by_name(request.name)
        if existing is not None:
            logger.warning(
                "Skill '%s' already exists (id=%s), returning existing",
                request.name,
                existing.id,
            )
            return existing

        # 安全扫描
        scan_result = self.scanner.scan(request.content)

        skill = SkillMetadata(
            name=request.name,
            description=request.description,
            content=request.content,
            category=getattr(request, "category", ""),
            tags=request.tags,
            fallback_for_toolsets=request.fallback_for_toolsets,
            requires_tools=request.requires_tools,
            requires_toolsets=getattr(request, "requires_toolsets", []),
            fallback_for_tools=getattr(request, "fallback_for_tools", []),
            created_by=created_by,
            safety_level=scan_result.level,
            status=(
                SkillStatus.DANGEROUS
                if scan_result.level in ("critical", "high")
                else SkillStatus.ACTIVE
            ),
        )

        await self.store.save(skill)
        logger.info(
            "Skill created: name=%s id=%s safety=%s category=%s by=%s",
            skill.name,
            skill.id,
            skill.safety_level,
            skill.category,
            created_by,
        )

        if scan_result.findings:
            logger.warning(
                "Skill '%s' has %d safety findings: %s",
                skill.name,
                len(scan_result.findings),
                [(f.category, f.matched_text[:30]) for f in scan_result.findings],
            )

        return skill

    # ── 读取 ───────────────────────────────────────────────────────────

    async def get_skill(self, skill_id: str) -> SkillMetadata:
        """按 ID 获取 Skill."""
        skill = await self.store.get(skill_id)
        if skill is None:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")
        return skill

    async def list_skills(
        self,
        status: str | None = None,
        tag: str | None = None,
        safety_level: str | None = None,
        query: str | None = None,
    ) -> list[SkillMetadata]:
        """列出所有 Skill，支持过滤."""
        return await self.store.list_all(
            status=status,
            tag=tag,
            safety_level=safety_level,
            query=query,
        )

    async def get_active_skills(
        self,
        available_tools: list[str],
    ) -> list[SkillMetadata]:
        """获取当前环境下可见的活跃 Skill（经条件激活过滤）."""
        all_active = await self.store.list_all(status="active")
        return self.activator.filter_skills(all_active, available_tools)

    # ── 全量编辑 ─────────────────────────────────────────────────────

    async def edit_skill(
        self,
        skill_id: str,
        new_content: str,
        reason: str = "",
        edited_by: str = "agent",
    ) -> SkillMetadata:
        """全量替换 Skill 内容（区别于 patch 的精准修改）.

        action='edit' — 整体替换内容，适用于大幅重写场景。
        """
        skill = await self.store.get(skill_id)
        if skill is None:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")

        # 大小限制
        if len(new_content) > MAX_SKILL_MD_CHARS:
            raise SizeLimitExceededError(
                f"SKILL.md content exceeds {MAX_SKILL_MD_CHARS:,} character limit"
            )

        # Frontmatter 校验（edit 路径同样强制）
        self.validate_frontmatter(new_content)

        old_content = skill.content

        # 重新安全扫描
        scan_result = self.scanner.scan(new_content)

        # 记录为补丁历史
        patch_record = SkillPatch(
            old_string="[full content replaced]",
            new_string=f"[{len(new_content)} chars]",
            reason=reason or "Full content edit",
            applied_by=edited_by,
        )

        skill.content = new_content
        skill.version += 1
        skill.updated_at = datetime.now(timezone.utc)
        skill.safety_level = scan_result.level
        skill.patch_history.append(patch_record)

        if scan_result.level in ("critical", "high"):
            skill.status = SkillStatus.DANGEROUS

        await self.store.update(skill)
        logger.info(
            "Skill edited: name=%s version=%d safety=%s by=%s",
            skill.name,
            skill.version,
            skill.safety_level,
            edited_by,
        )
        return skill

    # ── 热补丁 ─────────────────────────────────────────────────────────

    async def patch_skill(
        self,
        skill_id: str,
        patch: SkillPatchRequest,
        applied_by: str = "agent",
    ) -> SkillMetadata:
        """对 Skill 执行热补丁.

        算法：
        1. 验证 old_string 恰好出现 1 次
        2. 就地替换
        3. 重新安全扫描
        4. 追加补丁历史
        5. 版本号 +1
        6. 如果安全等级变为 critical/high → 自动隔离

        注: 如果精确匹配失败，源码中使用 fuzzy_find_and_replace 作为兜底。
        fuzzy matching 会尝试忽略空白差异和缩进差异进行模糊定位。
        当前实现中使用精确匹配 + 空白标准化兜底。

        设计选择：
        - 保留上下文：其他部分不因一处失效而丢失
        - 最小化侵入：只修改确认有问题的片段
        - 可追溯性：补丁记录本身也是学习历史
        """
        skill = await self.store.get(skill_id)
        if skill is None:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")

        # 验证补丁目标唯一性
        occurrences = skill.content.count(patch.old_string)
        if occurrences == 0:
            # 尝试模糊匹配（fuzzy_find_and_replace 兜底）
            # 标准化空白后重试
            normalized_content = self._normalize_whitespace(skill.content)
            normalized_old = self._normalize_whitespace(patch.old_string)
            if normalized_old in normalized_content:
                logger.info(
                    "Exact match failed, fuzzy match succeeded for skill '%s' "
                    "(whitespace normalization). Reference: fuzzy_find_and_replace",
                    skill.name,
                )
                # 找到标准化后的位置，定位原文中对应片段替换
                new_content = self._fuzzy_replace(
                    skill.content, patch.old_string, patch.new_string
                )
                if new_content is not None:
                    return await self._apply_patch(
                        skill, new_content, patch, applied_by,
                        fuzzy=True,
                    )

            raise PatchTargetNotFoundError(
                f"String '{patch.old_string[:80]}...' not found in skill '{skill.name}'. "
                "Fuzzy matching (fuzzy_find_and_replace) also failed."
            )
        if occurrences > 1:
            raise AmbiguousPatchError(
                f"String appears {occurrences} times in skill '{skill.name}'. "
                "Provide a longer/more specific old_string to target exactly one occurrence."
            )

        # 就地替换
        new_content = skill.content.replace(patch.old_string, patch.new_string, 1)
        return await self._apply_patch(skill, new_content, patch, applied_by)

    async def _apply_patch(
        self,
        skill: SkillMetadata,
        new_content: str,
        patch: SkillPatchRequest,
        applied_by: str,
        fuzzy: bool = False,
    ) -> SkillMetadata:
        """应用补丁的公共逻辑."""
        # 重新安全扫描
        scan_result = self.scanner.scan(new_content)

        # 记录补丁
        reason = patch.reason
        if fuzzy:
            reason = f"[fuzzy match] {reason}" if reason else "[fuzzy match]"

        patch_record = SkillPatch(
            old_string=patch.old_string,
            new_string=patch.new_string,
            reason=reason,
            applied_by=applied_by,
        )

        # 更新 Skill
        skill.content = new_content
        skill.version += 1
        skill.updated_at = datetime.now(timezone.utc)
        skill.safety_level = scan_result.level
        skill.patch_history.append(patch_record)

        # 危险内容自动隔离
        if scan_result.level in ("critical", "high"):
            skill.status = SkillStatus.DANGEROUS
            logger.warning(
                "Skill '%s' auto-quarantined after patch: %s",
                skill.name,
                [(f.category, f.matched_text[:30]) for f in scan_result.findings],
            )

        await self.store.update(skill)
        logger.info(
            "Skill patched: name=%s version=%d safety=%s by=%s fuzzy=%s",
            skill.name,
            skill.version,
            skill.safety_level,
            applied_by,
            fuzzy,
        )
        return skill

    # ── 废弃/删除 ─────────────────────────────────────────────────────

    async def deprecate_skill(self, skill_id: str) -> SkillMetadata:
        """软删除：标记为 DEPRECATED（保留历史）.

        对应 action='delete' — 不物理删除，保留可追溯性。
        """
        skill = await self.store.get(skill_id)
        if skill is None:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")

        skill.status = SkillStatus.DEPRECATED
        skill.updated_at = datetime.now(timezone.utc)
        await self.store.update(skill)
        logger.info("Skill deprecated: name=%s id=%s", skill.name, skill.id)
        return skill

    # ── 文件操作 ─────────────────────────────────────────────────────

    async def write_file(
        self,
        skill_id: str,
        filename: str,
        content: str | bytes,
    ) -> str:
        """写入 Skill 附属文件 (action='write_file').

        使用原子写入模式（tempfile + os.replace）确保文件完整性。

        Args:
            skill_id: Skill ID
            filename: 文件名（相对于 Skill 目录）
            content: 文件内容（文本或二进制）

        Returns:
            写入文件的完整路径

        Raises:
            SkillNotFoundError: Skill 不存在
            SizeLimitExceededError: 文件超过 1 MiB
        """
        skill = await self.store.get(skill_id)
        if skill is None:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")

        # 大小限制检查
        content_bytes = content.encode("utf-8") if isinstance(content, str) else content
        if len(content_bytes) > MAX_SKILL_FILE_SIZE:
            raise SizeLimitExceededError(
                f"File '{filename}' exceeds {MAX_SKILL_FILE_SIZE:,} byte limit "
                f"(actual: {len(content_bytes):,})"
            )

        # 安全检查: 禁止路径穿越
        if ".." in filename or filename.startswith("/"):
            raise ValueError(f"Invalid filename: '{filename}' (path traversal detected)")

        # 确保 Skill 目录存在
        skill_dir = self._skill_store_path / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)

        target_path = skill_dir / filename

        # 原子写入: tempfile + os.replace
        # 避免写入中断导致的文件损坏
        mode = "w" if isinstance(content, str) else "wb"
        fd, tmp_path = tempfile.mkstemp(
            dir=str(skill_dir),
            prefix=f".{filename}.",
            suffix=".tmp",
        )
        try:
            if isinstance(content, str):
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
            else:
                with os.fdopen(fd, "wb") as f:
                    f.write(content)
            os.replace(tmp_path, str(target_path))
        except Exception:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        # 写入后执行结构检查（FR-04.6-04.7: scan_directory 集成）
        structural_result = self.scanner.scan_directory(skill_dir)
        if not structural_result.passed:
            # 结构检查不通过 → 回滚文件写入
            try:
                target_path.unlink(missing_ok=True)
            except OSError:
                pass
            issues = "; ".join(f.detail for f in structural_result.findings)
            raise ValueError(
                f"Structural scan failed after write_file: {issues}"
            )

        logger.info(
            "File written: skill=%s file=%s size=%d",
            skill.name,
            filename,
            len(content_bytes),
        )
        return str(target_path)

    async def remove_file(
        self,
        skill_id: str,
        filename: str,
    ) -> bool:
        """删除 Skill 附属文件 (action='remove_file').

        Args:
            skill_id: Skill ID
            filename: 文件名（相对于 Skill 目录）

        Returns:
            是否成功删除

        Raises:
            SkillNotFoundError: Skill 不存在
        """
        skill = await self.store.get(skill_id)
        if skill is None:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")

        # 安全检查: 禁止路径穿越
        if ".." in filename or filename.startswith("/"):
            raise ValueError(f"Invalid filename: '{filename}' (path traversal detected)")

        target_path = self._skill_store_path / skill.name / filename

        if not target_path.exists():
            logger.warning(
                "File not found for removal: skill=%s file=%s",
                skill.name,
                filename,
            )
            return False

        target_path.unlink()
        logger.info(
            "File removed: skill=%s file=%s",
            skill.name,
            filename,
        )
        return True

    # ── 使用统计 ───────────────────────────────────────────────────────

    async def record_skill_use(self, skill_id: str) -> None:
        """递增使用计数."""
        skill = await self.store.get(skill_id)
        if skill is None:
            return
        skill.use_count += 1
        skill.updated_at = datetime.now(timezone.utc)
        await self.store.update(skill)

    # ── Frontmatter 校验 ─────────────────────────────────────────────

    @staticmethod
    def validate_frontmatter(content: str) -> dict[str, str]:
        """校验 SKILL.md frontmatter 必须包含 name 和 description.

        支持 YAML frontmatter 格式:
        ---
        name: skill-name
        description: skill description
        ---

        Returns:
            解析出的 frontmatter 字典

        Raises:
            FrontmatterValidationError: 缺少必需字段
        """
        fm_match = re.match(
            r"^---\s*\n(.*?)\n---",
            content,
            re.DOTALL,
        )
        if not fm_match:
            raise FrontmatterValidationError(
                "SKILL.md must start with YAML frontmatter (---\\n...\\n---)"
            )

        fm_text = fm_match.group(1)
        fields: dict[str, str] = {}
        for line in fm_text.strip().split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()

        if "name" not in fields or not fields["name"]:
            raise FrontmatterValidationError(
                "SKILL.md frontmatter must include 'name' field"
            )
        if "description" not in fields or not fields["description"]:
            raise FrontmatterValidationError(
                "SKILL.md frontmatter must include 'description' field"
            )

        return fields

    # ── 内部工具方法 ─────────────────────────────────────────────────

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        """标准化空白，用于 fuzzy matching."""
        # 将连续空白压缩为单个空格，去除行首行尾空白
        lines = [line.strip() for line in text.split("\n")]
        return "\n".join(lines)

    @staticmethod
    def _fuzzy_replace(
        content: str,
        old_string: str,
        new_string: str,
    ) -> str | None:
        """模糊替换 — 标准化空白后定位替换.

        对齐源码中的 fuzzy_find_and_replace 逻辑：
        当精确匹配失败时，尝试忽略空白差异进行匹配。

        Returns:
            替换后的内容，或 None（如果模糊匹配也失败）
        """
        # 按行标准化后查找
        content_lines = content.split("\n")
        old_lines = old_string.split("\n")

        # 滑动窗口匹配
        old_stripped = [line.strip() for line in old_lines]
        window_size = len(old_stripped)

        for i in range(len(content_lines) - window_size + 1):
            window = [line.strip() for line in content_lines[i:i + window_size]]
            if window == old_stripped:
                # 找到匹配，替换原始内容
                before = "\n".join(content_lines[:i])
                after = "\n".join(content_lines[i + window_size:])
                parts = [p for p in [before, new_string, after] if p]
                return "\n".join(parts)

        return None
