"""双引擎自学习测试 — 验证计数器逻辑和触发机制.

注：此测试不依赖 Redis，使用内存 mock。
计数器按 agent 主循环迭代递增，NOT per tool call。
"""

from __future__ import annotations

import pytest

from hermes_evo.core.dual_engine import DualEngineLearner
from hermes_evo.core.review_agent import ReviewAgent
from hermes_evo.core.skill_manager import SkillManager
from hermes_evo.models.review import ReviewResult


class MockIterationTracker:
    """内存版迭代计数器（替代 Redis）."""

    def __init__(self):
        self._counters: dict[str, int] = {}

    async def increment(self, agent_id: str) -> int:
        self._counters[agent_id] = self._counters.get(agent_id, 0) + 1
        return self._counters[agent_id]

    async def reset(self, agent_id: str) -> None:
        self._counters[agent_id] = 0

    async def get_count(self, agent_id: str) -> int:
        return self._counters.get(agent_id, 0)


class MockReviewAgent:
    """Mock 审查 Agent — 总是返回 nothing_to_save."""

    async def analyze(self, conversation_history, existing_skills=None, combined_mode=False):
        return ReviewResult(
            nothing_to_save=True,
            reasoning="Mock: nothing to save",
        )


class MockSkillManager:
    """Mock Skill Manager — 最小实现."""

    async def list_skills(self, status=None):
        return []

    async def create_skill(self, request, created_by="test"):
        return None


class TestDualEngine:
    """双引擎自学习单元测试."""

    @pytest.fixture
    def tracker(self):
        return MockIterationTracker()

    @pytest.fixture
    def engine(self, tracker):
        return DualEngineLearner(
            skill_manager=MockSkillManager(),
            review_agent=MockReviewAgent(),
            tracker=tracker,
            threshold=5,
        )

    # ── 计数器按主循环迭代递增 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_counter_increments_per_loop_iteration(self, engine, tracker):
        """每次主循环迭代，计数器递增一次."""
        await engine.on_loop_iteration("agent-1", tool_calls=[
            {"name": "search", "args": {}, "result": "r1"},
            {"name": "read_file", "args": {}, "result": "r2"},
        ])
        # 一次迭代（含多个 tool call）只递增一次
        assert await tracker.get_count("agent-1") == 1

        await engine.on_loop_iteration("agent-1", tool_calls=[
            {"name": "write_file", "args": {}, "result": "r3"},
        ])
        assert await tracker.get_count("agent-1") == 2

    @pytest.mark.asyncio
    async def test_counter_not_per_tool_call(self, engine, tracker):
        """计数器不按 tool call 递增 — 单次迭代含 5 个 tool call 仍只 +1."""
        calls = [{"name": f"tool_{i}", "args": {}, "result": "r"} for i in range(5)]
        await engine.on_loop_iteration("agent-1", tool_calls=calls)
        assert await tracker.get_count("agent-1") == 1

    # ── Engine 1: 前台自觉 ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_engine1_resets_counter_via_loop_iteration(self, engine, tracker):
        """Engine 1: on_loop_iteration 中检测到 skill_manage create → 归零."""
        # 累积 3 次迭代
        for _ in range(3):
            await engine.on_loop_iteration("agent-1")
        assert await tracker.get_count("agent-1") == 3

        # 本轮迭代包含 skill_manage create → Engine 1 触发
        await engine.on_loop_iteration(
            "agent-1",
            tool_calls=[
                {"name": "search", "args": {}, "result": "r"},
                {"name": "skill_manage", "args": {"action": "create", "name": "new-skill"}, "result": "created"},
            ],
        )
        assert await tracker.get_count("agent-1") == 0

    @pytest.mark.asyncio
    async def test_engine1_resets_counter_via_on_tool_call(self, engine, tracker):
        """Engine 1: on_tool_call 向后兼容接口也能检测 create."""
        # 先用 on_loop_iteration 累积
        for _ in range(3):
            await engine.on_loop_iteration("agent-1")
        assert await tracker.get_count("agent-1") == 3

        # 用旧接口 on_tool_call 触发 Engine 1（不递增计数器，只检测 create）
        await engine.on_tool_call(
            "agent-1",
            "skill_manage",
            {"action": "create", "name": "new-skill"},
            "created",
        )
        assert await tracker.get_count("agent-1") == 0

    @pytest.mark.asyncio
    async def test_on_tool_call_does_not_increment(self, engine, tracker):
        """on_tool_call 不递增计数器（仅 on_loop_iteration 递增）."""
        await engine.on_tool_call("agent-1", "search", {}, "result")
        assert await tracker.get_count("agent-1") == 0  # 不递增

    # ── Engine 2: 后台巡检 ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_engine2_not_triggered_below_threshold(self, engine, tracker):
        """计数器低于阈值时，Engine 2 不触发."""
        for _ in range(3):
            await engine.on_loop_iteration("agent-1")

        result = await engine.check_background_inspection("agent-1", [])
        assert result is None

    @pytest.mark.asyncio
    async def test_engine2_triggered_at_threshold(self, engine, tracker):
        """计数器达到阈值时，Engine 2 触发."""
        for _ in range(5):
            await engine.on_loop_iteration("agent-1")

        result = await engine.check_background_inspection("agent-1", [])
        assert result is not None
        assert result.nothing_to_save is True
        # 触发后计数器归零
        assert await tracker.get_count("agent-1") == 0

    @pytest.mark.asyncio
    async def test_cross_task_accumulation(self, engine, tracker):
        """跨任务累积：任务1 + 任务2 的迭代数超过阈值.

        计数器 NOT reset between tasks，跨任务累积。
        """
        # 任务 1: 3 次迭代
        for _ in range(3):
            await engine.on_loop_iteration("agent-1")
        # 不触发
        result = await engine.check_background_inspection("agent-1", [])
        assert result is None
        assert await tracker.get_count("agent-1") == 3

        # 任务 2: 3 次迭代 → 总计 6 >= 阈值 5
        for _ in range(3):
            await engine.on_loop_iteration("agent-1")
        result = await engine.check_background_inspection("agent-1", [])
        assert result is not None

    # ── 强制审查 ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_force_review_ignores_threshold(self, engine, tracker):
        """强制审查忽略阈值."""
        # 只有 1 次迭代，远低于阈值
        await engine.on_loop_iteration("agent-1")

        result = await engine.force_review("agent-1", [])
        assert result is not None
        assert await tracker.get_count("agent-1") == 0

    @pytest.mark.asyncio
    async def test_force_combined_review(self, engine, tracker):
        """联合审查（memory + skill）."""
        await engine.on_loop_iteration("agent-1")

        result = await engine.force_combined_review("agent-1", [])
        assert result is not None
        assert await tracker.get_count("agent-1") == 0

    # ── patch 不归零 ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_patch_does_not_reset_counter(self, engine, tracker):
        """skill_manage patch 不归零计数器（只有 create 才归零）."""
        for _ in range(3):
            await engine.on_loop_iteration("agent-1")

        await engine.on_loop_iteration(
            "agent-1",
            tool_calls=[
                {"name": "skill_manage", "args": {"action": "patch", "skill_id": "xxx"}, "result": "patched"},
            ],
        )
        # patch 不触发 Engine 1，计数器继续累积（3 + 1 = 4）
        assert await tracker.get_count("agent-1") == 4

    # ── Daemon Thread 启动 ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_launch_background_review_returns_thread(self, engine, tracker):
        """launch_background_review 返回 daemon thread."""
        for _ in range(5):
            await engine.on_loop_iteration("agent-1")

        thread = engine.launch_background_review("agent-1", [])
        assert thread.daemon is True
        assert thread.name.startswith("review-agent-")
        thread.join(timeout=5)  # 等待线程完成
