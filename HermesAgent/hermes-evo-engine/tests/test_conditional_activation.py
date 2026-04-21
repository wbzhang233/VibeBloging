"""条件激活测试."""

from hermes_evo.core.conditional_activation import ConditionalActivator
from hermes_evo.models.skill import SkillMetadata


class TestConditionalActivation:
    """ConditionalActivator 单元测试.

    对齐 HermesAgent 源码 prompt_builder.py _skill_should_show() 四条规则。
    """

    def test_no_conditions_pass_through(self, activator: ConditionalActivator):
        """无条件限制的 Skill 始终可见."""
        skill = SkillMetadata(name="basic", description="No conditions", content="...")
        result = activator.filter_skills([skill], ["web-fetch", "Bash"])
        assert len(result) == 1
        assert result[0].name == "basic"

    # ── 规则 1: fallback_for_toolsets ─────────────────────────────────

    def test_fallback_hidden_when_primary_toolset_available(
        self,
        activator: ConditionalActivator,
        skill_with_fallback: SkillMetadata,
    ):
        """主工具集中有工具可用时，备用 Skill 隐藏."""
        result = activator.filter_skills(
            [skill_with_fallback],
            ["web-fetch", "Bash"],  # "web-fetch" 属于 "web" 工具集
        )
        assert len(result) == 0

    def test_fallback_visible_when_primary_toolset_absent(
        self,
        activator: ConditionalActivator,
        skill_with_fallback: SkillMetadata,
    ):
        """主工具集中无工具可用时，备用 Skill 可见."""
        result = activator.filter_skills(
            [skill_with_fallback],
            ["Bash"],  # 无 web 类工具
        )
        assert len(result) == 1

    # ── 规则 2: requires_tools ────────────────────────────────────────

    def test_requires_hidden_when_dependency_missing(
        self,
        activator: ConditionalActivator,
        skill_with_requires: SkillMetadata,
    ):
        """依赖工具缺失时，Skill 隐藏."""
        result = activator.filter_skills(
            [skill_with_requires],
            ["Bash"],  # 缺少 "web-fetch"
        )
        assert len(result) == 0

    def test_requires_visible_when_dependency_present(
        self,
        activator: ConditionalActivator,
        skill_with_requires: SkillMetadata,
    ):
        """依赖工具齐全时，Skill 可见."""
        result = activator.filter_skills(
            [skill_with_requires],
            ["web-fetch", "Bash"],
        )
        assert len(result) == 1

    # ── 规则 3: requires_toolsets ─────────────────────────────────────

    def test_requires_toolsets_hidden_when_no_toolset_available(
        self,
        activator: ConditionalActivator,
    ):
        """所有指定工具集均无可用工具时，Skill 隐藏."""
        skill = SkillMetadata(
            name="needs-web-or-browser",
            description="",
            content="...",
            requires_toolsets=["search", "browser"],
        )
        result = activator.filter_skills([skill], ["Bash"])  # 无 search/browser 工具
        assert len(result) == 0

    def test_requires_toolsets_visible_when_any_toolset_available(
        self,
        activator: ConditionalActivator,
    ):
        """至少一个指定工具集有可用工具时，Skill 可见."""
        skill = SkillMetadata(
            name="needs-web-or-browser",
            description="",
            content="...",
            requires_toolsets=["search", "browser"],
        )
        result = activator.filter_skills(
            [skill],
            ["Brave", "Bash"],  # Brave 属于 search 工具集
        )
        assert len(result) == 1

    # ── 规则 4: fallback_for_tools ────────────────────────────────────

    def test_fallback_for_tools_hidden_when_tool_available(
        self,
        activator: ConditionalActivator,
    ):
        """指定工具本身可用时，备用 Skill 隐藏."""
        skill = SkillMetadata(
            name="brave-fallback",
            description="",
            content="...",
            fallback_for_tools=["Brave"],
        )
        result = activator.filter_skills([skill], ["Brave", "Bash"])
        assert len(result) == 0

    def test_fallback_for_tools_visible_when_tool_absent(
        self,
        activator: ConditionalActivator,
    ):
        """指定工具不可用时，备用 Skill 可见."""
        skill = SkillMetadata(
            name="brave-fallback",
            description="",
            content="...",
            fallback_for_tools=["Brave"],
        )
        result = activator.filter_skills([skill], ["Bash"])
        assert len(result) == 1

    # ── 混合过滤 ─────────────────────────────────────────────────────

    def test_mixed_filtering(self, activator: ConditionalActivator):
        """混合过滤：多个 Skill 同时应用不同规则."""
        skills = [
            SkillMetadata(name="basic", description="", content="..."),
            SkillMetadata(
                name="fallback",
                description="",
                content="...",
                fallback_for_toolsets=["web"],
            ),
            SkillMetadata(
                name="advanced",
                description="",
                content="...",
                requires_tools=["web-fetch"],
            ),
        ]
        result = activator.filter_skills(skills, ["web-fetch"])
        # basic: 通过（无条件）
        # fallback: 隐藏（web 工具集中 web-fetch 可用）
        # advanced: 通过（web-fetch 可用）
        assert len(result) == 2
        names = {s.name for s in result}
        assert "basic" in names
        assert "advanced" in names

    def test_empty_tools_list(self, activator: ConditionalActivator):
        """空工具列表：备用可见，依赖隐藏."""
        skills = [
            SkillMetadata(
                name="fallback",
                description="",
                content="...",
                fallback_for_toolsets=["web"],
            ),
            SkillMetadata(
                name="advanced",
                description="",
                content="...",
                requires_tools=["web-fetch"],
            ),
        ]
        result = activator.filter_skills(skills, [])
        # fallback: 可见（web 工具集中无工具可用，备用需要出场）
        # advanced: 隐藏（缺少 web-fetch）
        assert len(result) == 1
        assert result[0].name == "fallback"

    def test_all_four_rules_combined(self, activator: ConditionalActivator):
        """同时测试四条规则."""
        skills = [
            # 规则1: fallback_for_toolsets
            SkillMetadata(
                name="ddg-search",
                description="",
                content="...",
                fallback_for_toolsets=["search"],
            ),
            # 规则2: requires_tools
            SkillMetadata(
                name="deep-research",
                description="",
                content="...",
                requires_tools=["web-fetch", "Brave"],
            ),
            # 规则3: requires_toolsets
            SkillMetadata(
                name="auto-browse",
                description="",
                content="...",
                requires_toolsets=["browser"],
            ),
            # 规则4: fallback_for_tools
            SkillMetadata(
                name="brave-alt",
                description="",
                content="...",
                fallback_for_tools=["Brave"],
            ),
        ]
        result = activator.filter_skills(skills, ["Brave", "web-fetch"])
        # ddg-search: 隐藏（search 中 Brave 可用 → 规则 1 触发）
        # deep-research: 通过（web-fetch 和 Brave 都可用 → 规则 2 通过）
        # auto-browse: 隐藏（browser 工具集中无 Brave/web-fetch → 需检查 registry）
        # brave-alt: 隐藏（Brave 可用 → 规则 4 触发）
        names = {s.name for s in result}
        assert "ddg-search" not in names
        assert "deep-research" in names
        assert "brave-alt" not in names
