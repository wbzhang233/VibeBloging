"""跨任务迭代计数器 — _iters_since_skill 的 Redis 持久化实现.

对齐 run_agent.py line 8182：计数器按 agent 主循环迭代递增，NOT per tool call。

跨任务累积示例：
  任务1：8 次主循环迭代 → _iters_since_skill = 8
  任务2：3 次主循环迭代 → _iters_since_skill = 11 → 触发后台巡检！

计数器跨任务累积（NOT reset between tasks），
Engine 1（前台自觉）触发时归零，Engine 2（后台巡检）完成后也归零。
"""

from __future__ import annotations

import logging

from hermes_evo.infra.redis_client import get_redis

logger = logging.getLogger(__name__)

_KEY_PREFIX = "hermes:iters:"
_TTL_SECONDS = 7 * 24 * 3600  # 7 天 TTL，防止孤立 Agent 的计数器永不过期


class IterationTracker:
    """基于 Redis 的跨任务迭代计数器."""

    async def increment(self, agent_id: str) -> int:
        """递增并返回新计数."""
        redis = await get_redis()
        key = f"{_KEY_PREFIX}{agent_id}"
        count = await redis.incr(key)
        await redis.expire(key, _TTL_SECONDS)
        return count

    async def reset(self, agent_id: str) -> None:
        """归零（Engine 1 触发 或 Engine 2 完成后）."""
        redis = await get_redis()
        key = f"{_KEY_PREFIX}{agent_id}"
        await redis.set(key, 0, ex=_TTL_SECONDS)
        logger.info("Iteration counter reset for agent %s", agent_id)

    async def get_count(self, agent_id: str) -> int:
        """获取当前计数."""
        redis = await get_redis()
        key = f"{_KEY_PREFIX}{agent_id}"
        value = await redis.get(key)
        return int(value) if value else 0
