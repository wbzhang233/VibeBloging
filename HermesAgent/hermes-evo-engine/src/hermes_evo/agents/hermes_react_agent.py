"""Hermes ReActAgent — 扩展 AgentScope ReActAgent 实现自进化.

核心扩展：
1. 注入 SKILLS_GUIDANCE 三条指令到系统提示
2. 注册 skill_manage 为 Toolkit 工具函数
3. 通过 post-hook 通知双引擎 on_tool_call
4. 任务完成后触发 check_background_inspection
5. 任务开始前加载活跃 Skill 列表到上下文
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from hermes_evo.agents.skill_tools import SKILLS_GUIDANCE, create_skill_manage_tool
from hermes_evo.core.dual_engine import DualEngineLearner
from hermes_evo.core.skill_manager import SkillManager
from hermes_evo.models.agent import ExecutionRecord

logger = logging.getLogger(__name__)


class HermesReActAgent:
    """自进化 ReActAgent.

    包装 AgentScope 的 ReActAgent，添加自进化能力。
    当 AgentScope 不可用时，退化为简单的 LLM 调用模式。

    架构：
    ┌──────────────────────────────────────┐
    │  HermesReActAgent                     │
    │  ┌────────────────────────────────┐  │
    │  │ AgentScope ReActAgent          │  │
    │  │  + SKILLS_GUIDANCE prompt      │  │
    │  │  + skill_manage tool           │  │
    │  └────────────────────────────────┘  │
    │  ┌────────────────────────────────┐  │
    │  │ DualEngineLearner              │  │
    │  │  Engine 1: on_tool_call hook   │  │
    │  │  Engine 2: post-task review    │  │
    │  └────────────────────────────────┘  │
    └──────────────────────────────────────┘
    """

    def __init__(
        self,
        agent_id: str | None = None,
        name: str = "HermesAgent",
        sys_prompt: str = "",
        skill_manager: SkillManager | None = None,
        dual_engine: DualEngineLearner | None = None,
        available_tools: list[str] | None = None,
        model_config: dict | None = None,
        max_iters: int = 20,
    ) -> None:
        self.agent_id = agent_id or str(uuid4())
        self.name = name
        self.skill_manager = skill_manager or SkillManager()
        self.dual_engine = dual_engine
        self.available_tools = available_tools or []
        self.max_iters = max_iters
        self._model_config = model_config or {}

        # 构建增强系统提示
        self._sys_prompt = self._build_system_prompt(sys_prompt)

        # 对话历史（用于 Engine 2 审查）
        self._conversation_history: list[dict] = []

        # 工具调用记录
        self._tool_calls: list[dict] = []
        self._skills_created: list[str] = []
        self._skills_patched: list[str] = []

        # 初始化 AgentScope Agent（如果可用）
        self._agent = None
        self._init_agentscope_agent()

    def _build_system_prompt(self, base_prompt: str) -> str:
        """构建包含 SKILLS_GUIDANCE 的增强系统提示."""
        parts = [base_prompt] if base_prompt else []
        parts.append(SKILLS_GUIDANCE)
        return "\n\n".join(parts)

    def _init_agentscope_agent(self) -> None:
        """初始化 AgentScope ReActAgent."""
        try:
            from agentscope.agents import ReActAgent
            from agentscope.models import DashScopeChatWrapper
            from agentscope.tool import Toolkit

            # 创建 Toolkit 并注册 skill_manage
            toolkit = Toolkit()
            skill_manage_fn = create_skill_manage_tool(self.skill_manager)
            toolkit.add(skill_manage_fn, name="skill_manage")

            # 创建模型
            model = DashScopeChatWrapper(
                config_name=f"{self.name}_model",
                model_name=self._model_config.get("model_name", "qwen-max"),
                api_key=self._model_config.get("api_key", ""),
            )

            self._agent = ReActAgent(
                name=self.name,
                sys_prompt=self._sys_prompt,
                model=model,
                toolkit=toolkit,
                max_iters=self.max_iters,
            )
            logger.info("AgentScope ReActAgent initialized: %s", self.name)

        except ImportError:
            logger.warning(
                "AgentScope not installed. HermesReActAgent running in mock mode."
            )
        except Exception as e:
            logger.error("Failed to init AgentScope agent: %s", e)

    async def execute(self, instruction: str, context: dict | None = None) -> ExecutionRecord:
        """执行一个任务.

        完整流程：
        1. 加载活跃 Skill 到上下文
        2. 执行 Agent 推理循环
        3. 每次工具调用 → 通知 Engine 1
        4. 任务完成 → 触发 Engine 2 检查
        5. 返回执行记录
        """
        record = ExecutionRecord(
            task_id=str(uuid4()),
            agent_id=self.agent_id,
        )

        # 重置当前任务的记录
        self._tool_calls = []
        self._skills_created = []
        self._skills_patched = []

        # 1. 加载活跃 Skill 到上下文
        skill_context = await self._load_skill_context()

        # 2. 构建完整输入
        full_instruction = instruction
        if skill_context:
            full_instruction = f"{skill_context}\n\n---\n\n{instruction}"
        if context:
            ctx_str = "\n".join(f"- {k}: {v}" for k, v in context.items())
            full_instruction = f"Context:\n{ctx_str}\n\n{full_instruction}"

        # 3. 执行
        try:
            result_text = await self._run_agent(full_instruction)
            record.success = True
            record.result = result_text
        except Exception as e:
            logger.error("Agent execution failed: %s", e)
            record.success = False
            record.result = f"Error: {e}"

        record.completed_at = datetime.now(timezone.utc)
        record.tool_calls = self._tool_calls
        record.skills_created = self._skills_created
        record.skills_patched = self._skills_patched

        # 4. 记录到对话历史
        self._conversation_history.append(
            {"role": "user", "content": instruction}
        )
        self._conversation_history.append(
            {"role": "assistant", "content": record.result}
        )

        # 5. Engine 2 检查
        if self.dual_engine:
            try:
                review = await self.dual_engine.check_background_inspection(
                    self.agent_id,
                    self._conversation_history,
                )
                if review and not review.nothing_to_save:
                    logger.info(
                        "Engine 2 produced %d skill(s) after task %s",
                        len(review.candidates),
                        record.task_id,
                    )
            except Exception as e:
                logger.error("Engine 2 check failed: %s", e)

        return record

    async def _load_skill_context(self) -> str:
        """加载活跃 Skill 摘要到 Agent 上下文."""
        try:
            skills = await self.skill_manager.get_active_skills(self.available_tools)
            if not skills:
                return ""
            lines = ["## Available Skills (use skill_manage to interact):", ""]
            for skill in skills:
                lines.append(f"- **{skill.name}** (id={skill.id}): {skill.description}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning("Failed to load skill context: %s", e)
            return ""

    async def _run_agent(self, instruction: str) -> str:
        """执行 Agent 推理循环.

        如果 AgentScope 可用，使用 ReActAgent。
        否则使用简单模式返回说明。

        对齐源码: 每次主循环迭代调用 on_loop_iteration()（而非每次工具调用），
        计数器按 agent loop iteration 递增。
        """
        if self._agent is not None:
            try:
                from agentscope.message import Msg

                msg = Msg(name="user", content=instruction, role="user")
                response = self._agent(msg)

                # 收集本轮迭代的所有工具调用
                iteration_tool_calls: list[dict] = []
                if hasattr(response, "metadata"):
                    for tc in response.metadata.get("tool_calls", []):
                        iteration_tool_calls.append(tc)
                        self._tool_calls.append(tc)

                # FR-06.3: 每次主循环迭代通知 DualEngineLearner
                # 对齐 run_agent.py:8182 — 按 loop iteration 递增计数器
                if self.dual_engine:
                    await self.dual_engine.on_loop_iteration(
                        self.agent_id,
                        tool_calls=iteration_tool_calls,
                    )

                return response.content if hasattr(response, "content") else str(response)
            except Exception as e:
                logger.error("AgentScope execution error: %s", e)
                return f"AgentScope error: {e}"
        else:
            # Mock 模式 — 仍然递增计数器以保持行为一致
            if self.dual_engine:
                await self.dual_engine.on_loop_iteration(
                    self.agent_id,
                    tool_calls=[],
                )

            logger.info("Running in mock mode for instruction: %s", instruction[:80])
            return (
                f"[Mock Mode] Received instruction: {instruction[:200]}\n"
                f"Agent {self.name} (id={self.agent_id}) would process this with "
                f"AgentScope ReActAgent + {len(self.available_tools)} tools."
            )
