"""测试配置与 Fixtures."""

from __future__ import annotations

import pytest

from hermes_evo.core.conditional_activation import ConditionalActivator
from hermes_evo.core.safety_scanner import SafetyScanner
from hermes_evo.models.skill import SkillCreateRequest, SkillMetadata, SkillStatus


@pytest.fixture
def scanner() -> SafetyScanner:
    return SafetyScanner()


@pytest.fixture
def activator() -> ConditionalActivator:
    return ConditionalActivator()


@pytest.fixture
def sample_skill() -> SkillMetadata:
    return SkillMetadata(
        name="test-skill",
        description="A test skill for unit testing",
        content="Step 1: Do something\nStep 2: Do something else\nStep 3: Verify result",
        tags=["test", "example"],
    )


@pytest.fixture
def sample_create_request() -> SkillCreateRequest:
    return SkillCreateRequest(
        name="new-skill",
        description="A newly created skill",
        content="Step 1: First action\nStep 2: Second action",
        tags=["new"],
    )


@pytest.fixture
def skill_with_fallback() -> SkillMetadata:
    return SkillMetadata(
        name="duckduckgo-search",
        description="Fallback search when web tool is unavailable",
        content="Use DuckDuckGo API to search...",
        fallback_for_toolsets=["web"],
    )


@pytest.fixture
def skill_with_requires() -> SkillMetadata:
    return SkillMetadata(
        name="deep-research",
        description="Deep research requiring web-fetch",
        content="Use web-fetch to gather information...",
        requires_tools=["web-fetch"],
    )


@pytest.fixture
def dangerous_skill_content() -> str:
    return "Step 1: Run eval(user_input)\nStep 2: Execute rm -rf /tmp\nPassword: sk-abc123secret"
