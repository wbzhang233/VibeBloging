"""skill_manage() 工具函数 — 注册到 AgentScope Toolkit 供 Agent 调用.

这是 Agent 与自进化系统之间的桥梁。Agent 通过自然语言推理决定
何时调用此工具，工具内部委托给 SkillManager。

对齐 HermesAgent 源码：
  - SKILLS_GUIDANCE 注入到 Agent 系统提示
  - 六种操作: create | edit | patch | delete | read | list
  - write_file / remove_file 通过单独参数处理
"""

from __future__ import annotations

from hermes_evo.core.skill_manager import SkillManager
from hermes_evo.models.skill import SkillCreateRequest, SkillPatchRequest

# SKILLS_GUIDANCE — 注入到 Agent 系统提示（对齐源码原文）
SKILLS_GUIDANCE = (
    "After completing a complex task (5+ tool calls), fixing a tricky error, "
    "or discovering a non-trivial workflow, save the approach as a "
    "skill with skill_manage so you can reuse it next time.\n"
    "When using a skill and finding it outdated, incomplete, or wrong, "
    "patch it immediately with skill_manage(action='patch') — don't wait to be asked. "
    "Skills that aren't maintained become liabilities."
)


def create_skill_manage_tool(skill_manager: SkillManager):
    """创建绑定到特定 SkillManager 实例的 skill_manage 工具函数.

    返回的函数可以注册到 AgentScope Toolkit。
    支持六种操作: create | edit | patch | delete | read | list
    """

    async def skill_manage(
        action: str,
        name: str = "",
        description: str = "",
        content: str = "",
        category: str = "",
        skill_id: str = "",
        old_string: str = "",
        new_string: str = "",
        reason: str = "",
        tags: str = "",
        filename: str = "",
    ) -> str:
        """管理 Skill：创建、编辑、热补丁、删除、查看、列出，以及文件操作。

        Args:
            action: 操作类型 - "create" | "edit" | "patch" | "delete" | "read" | "list"
                    附加: "write_file" | "remove_file"
            name: Skill 名称（create 时必需）
            description: Skill 描述（create 时必需）
            content: Skill 正文内容（create/edit/write_file 时必需）
            category: Skill 分类（create 时可选）
            skill_id: Skill ID（edit/patch/delete/read/write_file/remove_file 时必需）
            old_string: 要替换的旧字符串（patch 时必需）
            new_string: 替换后的新字符串（patch 时必需）
            reason: 操作原因说明（patch/edit/delete 时可选）
            tags: 逗号分隔的标签（create 时可选）
            filename: 文件名（write_file/remove_file 时必需）

        Returns:
            操作结果描述
        """
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        if action == "create":
            if not name or not content:
                return "Error: 'name' and 'content' are required for action='create'"
            skill = await skill_manager.create_skill(
                SkillCreateRequest(
                    name=name,
                    description=description or name,
                    content=content,
                    category=category,
                    tags=tag_list,
                ),
                created_by="proactive",
            )
            return (
                f"Skill '{skill.name}' created successfully.\n"
                f"  id: {skill.id}\n"
                f"  category: {skill.category}\n"
                f"  safety_level: {skill.safety_level}\n"
                f"  status: {skill.status.value}"
            )

        elif action == "edit":
            if not skill_id or not content:
                return (
                    "Error: 'skill_id' and 'content' "
                    "are required for action='edit'"
                )
            skill = await skill_manager.edit_skill(
                skill_id,
                new_content=content,
                reason=reason,
                edited_by="proactive",
            )
            return (
                f"Skill '{skill.name}' edited to version {skill.version}.\n"
                f"  safety_level: {skill.safety_level}"
            )

        elif action == "patch":
            if not skill_id or not old_string or not new_string:
                return (
                    "Error: 'skill_id', 'old_string', and 'new_string' "
                    "are required for action='patch'"
                )
            skill = await skill_manager.patch_skill(
                skill_id,
                SkillPatchRequest(
                    old_string=old_string,
                    new_string=new_string,
                    reason=reason,
                ),
                applied_by="proactive",
            )
            return (
                f"Skill '{skill.name}' patched to version {skill.version}.\n"
                f"  safety_level: {skill.safety_level}"
            )

        elif action == "delete":
            if not skill_id:
                return "Error: 'skill_id' is required for action='delete'"
            skill = await skill_manager.deprecate_skill(skill_id)
            return f"Skill '{skill.name}' deprecated (soft-deleted)."

        elif action == "read":
            if not skill_id:
                return "Error: 'skill_id' is required for action='read'"
            skill = await skill_manager.get_skill(skill_id)
            return (
                f"# {skill.name}\n"
                f"version: {skill.version} | status: {skill.status.value} | "
                f"category: {skill.category}\n"
                f"---\n{skill.content}"
            )

        elif action == "list":
            skills = await skill_manager.list_skills(status="active")
            if not skills:
                return "No active skills found."
            lines = [f"- **{s.name}** (id={s.id}): {s.description}" for s in skills]
            return f"Active skills ({len(skills)}):\n" + "\n".join(lines)

        elif action == "write_file":
            if not skill_id or not filename or not content:
                return (
                    "Error: 'skill_id', 'filename', and 'content' "
                    "are required for action='write_file'"
                )
            path = await skill_manager.write_file(skill_id, filename, content)
            return f"File written: {path}"

        elif action == "remove_file":
            if not skill_id or not filename:
                return (
                    "Error: 'skill_id' and 'filename' "
                    "are required for action='remove_file'"
                )
            removed = await skill_manager.remove_file(skill_id, filename)
            if removed:
                return f"File '{filename}' removed."
            else:
                return f"File '{filename}' not found."

        else:
            return (
                f"Unknown action: '{action}'. "
                "Use: create | edit | patch | delete | read | list | write_file | remove_file"
            )

    return skill_manage
