"""Redis 客户端 — 迭代计数器、缓存、Pub/Sub."""

from __future__ import annotations

import redis.asyncio as aioredis

from hermes_evo.config import settings

# 全局连接池（懒初始化）
_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """获取 Redis 异步客户端（单例）."""
    global _pool  # noqa: PLW0603
    if _pool is None:
        _pool = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
        )
    return _pool


async def close_redis() -> None:
    """关闭 Redis 连接池."""
    global _pool  # noqa: PLW0603
    if _pool is not None:
        await _pool.aclose()
        _pool = None
