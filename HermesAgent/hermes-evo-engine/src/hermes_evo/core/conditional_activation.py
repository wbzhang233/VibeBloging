"""条件激活过滤 — 控制哪些 Skill 在当前环境中可见.

四条规则（对齐 HermesAgent 源码 prompt_builder.py 的 _skill_should_show()）：

1. fallback_for_toolsets: [web]
   -> 如果 web 工具集中任一工具已可用，此备用 Skill 隐藏。
      主工具在场时，备用 Skill 不占用 Context。

2. requires_tools: [web-fetch]
   -> 如果 web-fetch 工具不可用，此 Skill 隐藏，
      防止调用失败。

3. requires_toolsets: [search, browser]
   -> 如果指定的工具集中全部为空（无一可用），此 Skill 隐藏。
      与 requires_tools 不同：这里检查的是"至少一个工具集有内容"。

4. fallback_for_tools: [Brave]
   -> 如果 Brave 工具本身可用，此备用 Skill 隐藏。
      与 fallback_for_toolsets 不同：这里检查的是具体工具名而非工具集名。
"""

from __future__ import annotations

from hermes_evo.models.skill import SkillMetadata


# ── 工具集注册表（可扩展）────────────────────────────────────────────
# 映射工具集名称到其下辖的具体工具名列表
# 实际部署时从配置/API 动态加载
_DEFAULT_TOOLSET_REGISTRY: dict[str, list[str]] = {
    "web": ["web-fetch", "web-search", "Brave"],
    "search": ["web-search", "Brave", "duckduckgo"],
    "browser": ["web-fetch", "puppeteer", "playwright"],
    "code": ["Bash", "Computer", "file-editor"],
    "mcp": [],  # MCP 工具集动态注册
}


class ConditionalActivator:
    """根据当前可用工具过滤 Skill 列表.

    对齐 HermesAgent 源码 prompt_builder.py 的 _skill_should_show() 逻辑：
    四条规则按顺序求值，任一条触发 skip → Skill 不可见。
    """

    def __init__(
        self,
        toolset_registry: dict[str, list[str]] | None = None,
    ) -> None:
        """初始化.

        Args:
            toolset_registry: 工具集名称到具体工具名的映射。
                             如未指定，使用内置默认注册表。
        """
        self._toolset_registry = toolset_registry or _DEFAULT_TOOLSET_REGISTRY

    def _resolve_toolset(self, toolset_name: str) -> list[str]:
        """将工具集名称解析为其下辖的具体工具名列表."""
        return self._toolset_registry.get(toolset_name, [])

    def _toolset_has_available_tool(
        self,
        toolset_name: str,
        available_set: set[str],
    ) -> bool:
        """检查指定工具集中是否有至少一个工具可用."""
        tools_in_set = self._resolve_toolset(toolset_name)
        return any(t in available_set for t in tools_in_set)

    def filter_skills(
        self,
        skills: list[SkillMetadata],
        available_tools: list[str],
    ) -> list[SkillMetadata]:
        """返回当前环境下应该可见的 Skill 列表.

        对齐 _skill_should_show() 四条规则：

        1. fallback_for_toolsets — 主工具集可用时隐藏备用 Skill
        2. requires_tools — 缺少依赖工具时隐藏
        3. requires_toolsets — 所有指定工具集均无可用工具时隐藏
        4. fallback_for_tools — 指定工具本身可用时隐藏备用 Skill

        Args:
            skills: 全量 Skill 列表（仅 ACTIVE 状态）
            available_tools: 当前环境中已配置/可用的工具名列表

        Returns:
            过滤后的 Skill 列表
        """
        available_set = set(available_tools)
        result: list[SkillMetadata] = []

        for skill in skills:
            if not self._skill_should_show(skill, available_set):
                continue
            result.append(skill)

        return result

    def _skill_should_show(
        self,
        skill: SkillMetadata,
        available_set: set[str],
    ) -> bool:
        """判断单个 Skill 是否应该在当前环境中可见.

        对齐 HermesAgent 源码 prompt_builder.py 的同名函数。
        四条规则按顺序求值，任一条触发 → 返回 False。
        """
        # 规则 1: fallback_for_toolsets — 主工具集可用时，备用 Skill 不需要
        # 例: fallback_for_toolsets: ["web"]
        #     如果 web 工具集中任一工具（web-fetch, web-search 等）已可用 → 隐藏
        if skill.fallback_for_toolsets:
            if any(
                self._toolset_has_available_tool(ts, available_set)
                for ts in skill.fallback_for_toolsets
            ):
                return False

        # 规则 2: requires_tools — 缺少具体依赖工具时隐藏
        # 例: requires_tools: ["web-fetch"]
        #     如果 web-fetch 不在可用列表 → 隐藏
        if skill.requires_tools:
            if not all(t in available_set for t in skill.requires_tools):
                return False

        # 规则 3: requires_toolsets — 所有指定工具集均无可用工具时隐藏
        # 例: requires_toolsets: ["search", "browser"]
        #     如果 search 和 browser 工具集中都没有任何可用工具 → 隐藏
        #     只要有一个工具集有可用工具 → 通过
        if hasattr(skill, "requires_toolsets") and skill.requires_toolsets:
            if not any(
                self._toolset_has_available_tool(ts, available_set)
                for ts in skill.requires_toolsets
            ):
                return False

        # 规则 4: fallback_for_tools — 指定工具本身可用时隐藏备用 Skill
        # 例: fallback_for_tools: ["Brave"]
        #     如果 Brave 工具直接可用 → 隐藏此备用 Skill
        #     与规则 1 的区别：规则 1 检查工具集名，规则 4 检查具体工具名
        if hasattr(skill, "fallback_for_tools") and skill.fallback_for_tools:
            if any(t in available_set for t in skill.fallback_for_tools):
                return False

        return True
