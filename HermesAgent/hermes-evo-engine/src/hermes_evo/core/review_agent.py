"""Review Agent — 后台巡检执行体 (Engine 2).

独立的审查 Agent，使用 AgentScope ReActAgent 分析对话历史，
从中提取值得保存的经验 Skill。

对齐 HermesAgent 源码关键洞察：
  "只有包含绕路、犯错、迭代修正的经验才会被结晶为 Skill。
   纯粹顺利的任务反而不会触发 Skill 生成——挫折才是最好的老师。"

实现细节（对齐源码）：
  - threading.Thread(daemon=True) 启动
  - max_iterations=8
  - quiet_mode=True
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from hermes_evo.models.review import LearningCandidate, ReviewResult
from hermes_evo.models.skill import SkillMetadata

logger = logging.getLogger(__name__)

# ── 审查提示词（对齐源码原文）─────────────────────────────────────────

_SKILL_REVIEW_PROMPT = (
    "Review the conversation above and consider saving or updating a skill if appropriate.\n\n"
    "Focus on: was a non-trivial approach used to complete a task that required trial "
    "and error, or changing course due to experiential findings along the way, or did "
    "the user expect or desire a different method or outcome?\n\n"
    "If a relevant skill already exists, update it with what you learned. "
    "Otherwise, create a new skill if the approach is reusable.\n"
    "If nothing is worth saving, just say 'Nothing to save.' and stop."
)

# ── 联合审查提示词（memory + skill 同时处理）─────────────────────────

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

# ── JSON 输出格式指引 ─────────────────────────────────────────────────

_OUTPUT_FORMAT = """
For each identified skill, output a JSON array. Each element:
{
    "name": "<skill-name>",
    "description": "<one-line description>",
    "content": "<full step-by-step skill instructions>",
    "evidence": "<why this is worth saving>",
    "action": "create" | "update",
    "target_skill_id": "<id if action=update, else null>"
}

Rules:
- If an existing skill covers similar ground -> prefer UPDATE over CREATE.
- Do NOT save trivial one-step operations.
- Do NOT save standard library usage.
- Do NOT save skills too specific to be reusable.

If there is NOTHING valuable to save, respond with exactly:
{"nothing_to_save": true, "reasoning": "<brief explanation>"}
"""


class ReviewAgent:
    """后台巡检 Agent — 分析对话历史，提取可学习的 Skill.

    使用 AgentScope 的模型 API 进行 LLM 推理。

    对齐源码 run_agent.py:2195-2294:
    - max_iterations=8（限制审查 Agent 最多 8 次推理迭代）
    - quiet_mode=True（静默运行，不输出到终端）
    - _skill_nudge_interval=0（防止递归触发后台巡检）
    """

    # 源码对齐: max_iterations=8
    DEFAULT_MAX_ITERATIONS = 8

    def __init__(
        self,
        model_config: dict | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        quiet_mode: bool = True,
    ) -> None:
        self._model_config = model_config or {}
        self._model = None
        self.max_iterations = max_iterations
        self.quiet_mode = quiet_mode
        # 源码对齐: _skill_nudge_interval=0 防止递归巡检
        self._skill_nudge_interval = 0

    def _ensure_model(self):
        """懒初始化 AgentScope 模型."""
        if self._model is not None:
            return
        try:
            from agentscope.models import DashScopeChatWrapper

            self._model = DashScopeChatWrapper(
                config_name="review_agent_model",
                model_name=self._model_config.get("model_name", "qwen-max"),
                api_key=self._model_config.get("api_key", ""),
            )
        except ImportError:
            logger.warning(
                "AgentScope not installed, ReviewAgent will use mock mode"
            )
            self._model = None

    async def analyze(
        self,
        conversation_history: list[dict],
        existing_skills: list[SkillMetadata] | None = None,
        combined_mode: bool = False,
    ) -> ReviewResult:
        """分析对话历史，返回学习候选列表.

        Args:
            conversation_history: 对话消息列表 [{"role": ..., "content": ...}]
            existing_skills: 当前已有的 Skill 列表（用于去重判断）
            combined_mode: 是否使用联合审查模式（memory + skill 同时处理）

        Returns:
            ReviewResult 包含学习候选或 nothing_to_save=True
        """
        review_id = str(uuid4())

        # 选择提示词
        base_prompt = _COMBINED_REVIEW_PROMPT if combined_mode else _SKILL_REVIEW_PROMPT

        # 构建上下文
        skill_summaries = ""
        if existing_skills:
            summaries = [
                f"- {s.name} (id={s.id}): {s.description}"
                for s in existing_skills
            ]
            skill_summaries = (
                "\n\n## Existing Skills (for deduplication):\n"
                + "\n".join(summaries)
            )

        conversation_text = self._format_conversation(conversation_history)

        full_prompt = (
            f"{base_prompt}\n\n"
            f"{_OUTPUT_FORMAT}\n\n"
            f"{skill_summaries}\n\n"
            f"## Conversation History:\n{conversation_text}"
        )

        # 调用 LLM
        response_text = await self._call_llm(full_prompt)

        # 解析响应
        return self._parse_response(response_text, review_id, len(conversation_history))

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM 模型."""
        self._ensure_model()

        if self._model is not None:
            try:
                from agentscope.message import Msg

                msg = Msg(name="system", content=prompt, role="system")
                response = self._model([msg])
                return response.text if hasattr(response, "text") else str(response)
            except Exception as e:
                logger.error("LLM call failed: %s", e)
                return '{"nothing_to_save": true, "reasoning": "LLM call failed"}'
        else:
            # Mock 模式：无 AgentScope 时返回空结果
            logger.info("ReviewAgent running in mock mode (no AgentScope)")
            return '{"nothing_to_save": true, "reasoning": "Mock mode - no LLM available"}'

    def _parse_response(
        self,
        response_text: str,
        review_id: str,
        window: int,
    ) -> ReviewResult:
        """解析 LLM 响应为 ReviewResult."""
        try:
            data = json.loads(response_text.strip())
        except json.JSONDecodeError:
            # 尝试从 markdown 代码块中提取 JSON
            import re

            json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response_text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1).strip())
                except json.JSONDecodeError:
                    logger.warning("Failed to parse review response as JSON")
                    return ReviewResult(
                        review_id=review_id,
                        conversation_window=window,
                        nothing_to_save=True,
                        reasoning=f"Unparseable response: {response_text[:200]}",
                    )
            else:
                logger.warning("No JSON found in review response")
                return ReviewResult(
                    review_id=review_id,
                    conversation_window=window,
                    nothing_to_save=True,
                    reasoning=f"No JSON in response: {response_text[:200]}",
                )

        # 处理 nothing_to_save 响应
        if isinstance(data, dict) and data.get("nothing_to_save"):
            return ReviewResult(
                review_id=review_id,
                conversation_window=window,
                nothing_to_save=True,
                reasoning=data.get("reasoning", ""),
            )

        # 处理候选列表
        candidates_raw = data if isinstance(data, list) else [data]
        candidates = []
        for item in candidates_raw:
            if not isinstance(item, dict):
                continue
            candidates.append(
                LearningCandidate(
                    name=item.get("name", "unnamed"),
                    description=item.get("description", ""),
                    content=item.get("content", ""),
                    evidence=item.get("evidence", ""),
                    action=item.get("action", "create"),
                    target_skill_id=item.get("target_skill_id"),
                )
            )

        return ReviewResult(
            review_id=review_id,
            conversation_window=window,
            candidates=candidates,
            nothing_to_save=len(candidates) == 0,
            reasoning=f"Found {len(candidates)} learning candidate(s)",
        )

    @staticmethod
    def _format_conversation(history: list[dict]) -> str:
        """格式化对话历史为可读文本."""
        lines = []
        for msg in history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if len(content) > 500:
                content = content[:500] + "...[truncated]"
            lines.append(f"[{role}]: {content}")
        return "\n\n".join(lines)
