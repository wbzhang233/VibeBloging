"""双引擎自学习系统 — 自进化机制的算法核心.

对齐 HermesAgent 源码 run_agent.py（line 8182）：

Engine 1 — 前台自觉（Proactive Learning）
  Agent 执行任务中主动调用 skill_manage(action='create') 时，
  _iters_since_skill 计数器归零。

Engine 2 — 后台巡检（Background Inspection）
  计数器跨任务累积，达到阈值时，独立 review_agent 分析对话历史，
  提取值得保存的经验。

  跨任务累积示例：
    任务1（复杂代码审计）：8 次主循环迭代 → _iters_since_skill = 8
    任务2（简单查询）：    3 次主循环迭代 → _iters_since_skill = 11
    触发！后台巡检启动（阈值可配置，默认 10）

关键设计：
  - 计数器按 **agent 主循环迭代** 递增，NOT per tool call
    （run_agent.py line 8182: _iters_since_skill 在 main loop iteration 递增一次）
  - 计数器跨任务累积，不仅在单任务内（NOT reset between tasks）
  - Engine 1 触发时归零（前台自觉 reset）
  - Engine 2 完成后归零（后台巡检 reset）
  - 只有包含绕路、犯错、迭代修正的经验才会被结晶
  - Review agent: threading.Thread(daemon=True), max_iterations=8, quiet_mode=True

Combined Review:
  _COMBINED_REVIEW_PROMPT 支持 memory + skill 联合审查，
  单次调用同时处理记忆持久化和 Skill 提取。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from hermes_evo.config import settings
from hermes_evo.core.iteration_tracker import IterationTracker
from hermes_evo.core.review_agent import ReviewAgent
from hermes_evo.core.skill_manager import SkillManager
from hermes_evo.models.review import ReviewResult
from hermes_evo.models.skill import SkillCreateRequest

logger = logging.getLogger(__name__)


# ── Combined Review Prompt ────────────────────────────────────────────
# 对齐源码中的联合审查提示词，一次调用同时处理 memory 和 skill

_COMBINED_REVIEW_PROMPT = (
    "Review the conversation above. You have two tasks:\n\n"
    "1. **Memory**: Identify any facts, preferences, or context worth remembering "
    "for future conversations. Save them with memory_manage.\n\n"
    "2. **Skills**: Consider saving or updating a skill if appropriate.\n"
    "Focus on: was a non-trivial approach used to complete a task that required "
    "trial and error, or changing course due to experiential findings along the way, "
    "or did the user expect or desire a different method or outcome?\n\n"
    "If a relevant skill already exists, update it with what you learned. "
    "Otherwise, create a new skill if the approach is reusable.\n"
    "If nothing is worth saving for either category, just say 'Nothing to save.' and stop."
)


class DualEngineLearner:
    """双引擎自学习编排器.

    对齐 run_agent.py 源码设计：

    职责：
    1. 监听每次 agent 主循环迭代 → 维护迭代计数器
       (计数器按 agent loop iteration 递增，不是按 tool call)
    2. 检测 Engine 1 触发（skill_manage create）→ 计数器归零
    3. 任务完成后检查是否达到阈值 → 触发 Engine 2
    4. 协调 ReviewAgent 输出 → SkillManager 创建/更新

    Review Agent 实现细节（对齐源码）：
    - 使用 threading.Thread(daemon=True) 后台执行
    - max_iterations=8（review agent 自身最多 8 次推理迭代）
    - quiet_mode=True（不输出中间推理过程）

    计数器行为：
    - 跨任务累积（NOT reset between tasks）
    - Engine 1 创建 Skill 时归零
    - Engine 2 完成审查后归零
    """

    def __init__(
        self,
        skill_manager: SkillManager,
        review_agent: ReviewAgent | None = None,
        tracker: IterationTracker | None = None,
        threshold: int | None = None,
    ) -> None:
        self.skill_manager = skill_manager
        # 源码对齐: ReviewAgent 默认 max_iterations=8, quiet_mode=True
        # _skill_nudge_interval=0 防止递归巡检
        self.review_agent = review_agent or ReviewAgent(
            max_iterations=ReviewAgent.DEFAULT_MAX_ITERATIONS,
            quiet_mode=True,
        )
        self.tracker = tracker or IterationTracker()
        self.threshold = threshold or settings.review_threshold

    # ── Engine 1: 前台自觉 ─────────────────────────────────────────────

    async def on_loop_iteration(
        self,
        agent_id: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """每次 agent 主循环迭代后触发 — Engine 1 的入口.

        对齐 run_agent.py line 8182：计数器在 main loop iteration 递增一次，
        不是每个 tool call 递增一次。一次迭代可能包含多个 tool call。

        流程：
        1. 递增迭代计数器（每次主循环迭代 +1）
        2. 检查本轮迭代中是否包含 skill_manage(action='create')
           → 如果是，计数器归零（前台自觉机制已触发）

        Args:
            agent_id: Agent 标识
            tool_calls: 本轮迭代中所有的工具调用列表
                       [{"name": "...", "args": {...}, "result": "..."}]
        """
        count = await self.tracker.increment(agent_id)

        # 检查本轮迭代是否触发了 Engine 1
        if tool_calls:
            for call in tool_calls:
                tool_name = call.get("name", "")
                tool_args = call.get("args", {})
                if tool_name == "skill_manage" and tool_args.get("action") == "create":
                    await self.tracker.reset(agent_id)
                    logger.info(
                        "Engine 1 (Proactive) triggered: agent=%s created skill '%s', "
                        "counter reset from %d to 0",
                        agent_id,
                        tool_args.get("name", "unknown"),
                        count,
                    )
                    return

        logger.debug(
            "Loop iteration recorded: agent=%s counter=%d/%d",
            agent_id,
            count,
            self.threshold,
        )

    async def on_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        tool_args: dict,
        tool_result: str,
    ) -> None:
        """单个工具调用回调 — 仅用于 Engine 1 检测，不递增计数器.

        注意：计数器在 on_loop_iteration() 中递增（每次主循环迭代 +1），
        不在此方法中递增。此方法仅检查是否为 skill_manage create。

        保留此方法以向后兼容旧的调用方式。
        """
        # 仅检测 Engine 1 触发
        if tool_name == "skill_manage" and tool_args.get("action") == "create":
            count = await self.tracker.get_count(agent_id)
            await self.tracker.reset(agent_id)
            logger.info(
                "Engine 1 (Proactive) triggered via on_tool_call: agent=%s created skill '%s', "
                "counter reset from %d to 0",
                agent_id,
                tool_args.get("name", "unknown"),
                count,
            )

    # ── Engine 2: 后台巡检 ─────────────────────────────────────────────

    async def check_background_inspection(
        self,
        agent_id: str,
        conversation_history: list[dict],
    ) -> ReviewResult | None:
        """任务完成后检查是否触发 Engine 2.

        注意：计数器跨任务累积（cross-task accumulation），
        NOT reset between tasks。只有 Engine 1 触发或 Engine 2
        完成后才会归零。

        流程：
        1. 读取当前计数
        2. 如果 < 阈值 → 返回 None（不触发）
        3. 如果 >= 阈值 → 调用 ReviewAgent 分析
        4. 对每个候选 → 创建或更新 Skill
        5. 归零计数器
        """
        count = await self.tracker.get_count(agent_id)

        if count < self.threshold:
            logger.debug(
                "Engine 2 not triggered: agent=%s counter=%d/%d",
                agent_id,
                count,
                self.threshold,
            )
            return None

        logger.info(
            "Engine 2 (Background Inspection) triggered: agent=%s counter=%d >= threshold=%d",
            agent_id,
            count,
            self.threshold,
        )

        # 获取已有 Skill 用于去重
        existing_skills = await self.skill_manager.list_skills(status="active")

        # 执行审查
        result = await self.review_agent.analyze(
            conversation_history=conversation_history,
            existing_skills=existing_skills,
        )

        # 处理审查结果
        if not result.nothing_to_save:
            await self._apply_candidates(result)

        # 归零计数器（无论是否有候选）
        await self.tracker.reset(agent_id)

        logger.info(
            "Engine 2 completed: agent=%s candidates=%d nothing_to_save=%s",
            agent_id,
            len(result.candidates),
            result.nothing_to_save,
        )
        return result

    def launch_background_review(
        self,
        agent_id: str,
        conversation_history: list[dict],
    ) -> threading.Thread:
        """以 daemon 线程启动后台审查（对齐源码 threading.Thread(daemon=True)）.

        Review Agent 参数（对齐源码）：
        - daemon=True（主线程退出时自动终止）
        - max_iterations=8（review agent 自身最多 8 次推理迭代）
        - quiet_mode=True（不输出中间推理过程）

        Returns:
            启动的 daemon Thread 实例
        """
        import asyncio

        async def _run():
            await self.check_background_inspection(agent_id, conversation_history)

        def _thread_target():
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_run())
            finally:
                loop.close()

        thread = threading.Thread(
            target=_thread_target,
            name=f"review-agent-{agent_id}",
            daemon=True,  # 对齐源码: daemon=True
        )
        thread.start()
        logger.info(
            "Background review launched in daemon thread: agent=%s thread=%s",
            agent_id,
            thread.name,
        )
        return thread

    async def force_review(
        self,
        agent_id: str,
        conversation_history: list[dict],
    ) -> ReviewResult:
        """强制触发审查（忽略阈值），用于 API 手动触发.

        与 check_background_inspection 不同：
        - 不检查阈值
        - 始终执行
        - 同样归零计数器
        """
        logger.info("Force review triggered: agent=%s", agent_id)

        existing_skills = await self.skill_manager.list_skills(status="active")

        result = await self.review_agent.analyze(
            conversation_history=conversation_history,
            existing_skills=existing_skills,
        )

        if not result.nothing_to_save:
            await self._apply_candidates(result)

        await self.tracker.reset(agent_id)
        return result

    async def force_combined_review(
        self,
        agent_id: str,
        conversation_history: list[dict],
    ) -> ReviewResult:
        """强制触发联合审查（memory + skill 同时处理）.

        使用 _COMBINED_REVIEW_PROMPT 一次调用同时完成：
        1. 记忆持久化（识别值得记住的事实/偏好/上下文）
        2. Skill 提取（识别可复用的方法/流程）
        """
        logger.info("Force combined review triggered: agent=%s", agent_id)

        existing_skills = await self.skill_manager.list_skills(status="active")

        result = await self.review_agent.analyze(
            conversation_history=conversation_history,
            existing_skills=existing_skills,
            combined_mode=True,
        )

        if not result.nothing_to_save:
            await self._apply_candidates(result)

        await self.tracker.reset(agent_id)
        return result

    # ── 内部方法 ───────────────────────────────────────────────────────

    async def _apply_candidates(self, result: ReviewResult) -> None:
        """将审查候选应用为 Skill 创建/更新."""
        for candidate in result.candidates:
            try:
                if candidate.action == "create":
                    await self.skill_manager.create_skill(
                        SkillCreateRequest(
                            name=candidate.name,
                            description=candidate.description,
                            content=candidate.content,
                        ),
                        created_by="background_review",
                    )
                    logger.info(
                        "Engine 2 created skill: '%s' (evidence: %s)",
                        candidate.name,
                        candidate.evidence[:80],
                    )
                elif candidate.action == "update" and candidate.target_skill_id:
                    # 更新 = 用新内容全量替换（不同于热补丁）
                    skill = await self.skill_manager.get_skill(
                        candidate.target_skill_id
                    )
                    from hermes_evo.models.skill import SkillPatchRequest

                    await self.skill_manager.patch_skill(
                        candidate.target_skill_id,
                        SkillPatchRequest(
                            old_string=skill.content,
                            new_string=candidate.content,
                            reason=f"Background review update: {candidate.evidence[:100]}",
                        ),
                        applied_by="background_review",
                    )
                    logger.info(
                        "Engine 2 updated skill: '%s' (evidence: %s)",
                        candidate.name,
                        candidate.evidence[:80],
                    )
            except Exception as e:
                logger.error(
                    "Failed to apply candidate '%s': %s",
                    candidate.name,
                    e,
                )
