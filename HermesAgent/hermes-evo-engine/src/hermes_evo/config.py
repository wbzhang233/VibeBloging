"""Pydantic Settings — 统一配置中心."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量 / .env 加载的运行时配置."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="HERMES_",
        case_sensitive=False,
    )

    # ── LLM ────────────────────────────────────────────────────────────
    model_name: str = Field(
        default="qwen-max",
        description="AgentScope 使用的默认 LLM 模型名",
    )
    model_api_key: str = Field(
        default="",
        description="LLM API Key",
    )
    model_api_url: str = Field(
        default="",
        description="LLM API Base URL（留空使用默认）",
    )

    # ── 数据库 ─────────────────────────────────────────────────────────
    database_url: str = Field(
        default="mysql+aiomysql://hermes:hermes@localhost:3306/hermes_evo",
        description="TDSQL（MySQL 兼容）异步连接串",
    )

    # ── Redis ──────────────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 连接串",
    )

    # ── Skill Store ────────────────────────────────────────────────────
    skill_store_path: str = Field(
        default="./skill_store",
        description="Skill 文件持久化目录",
    )

    # ── 双引擎参数 ─────────────────────────────────────────────────────
    review_threshold: int = Field(
        default=10,
        description="触发后台巡检的迭代阈值（跨任务累积）",
    )
    max_agent_iters: int = Field(
        default=20,
        description="单次 Agent 任务最大推理迭代数",
    )

    # ── 安全扫描 ───────────────────────────────────────────────────────
    safety_scan_enabled: bool = Field(
        default=True,
        description="是否启用 Skill 安全扫描",
    )

    # ── Agent 池 ───────────────────────────────────────────────────────
    agent_pool_size: int = Field(
        default=5,
        description="Agent 并发池大小",
    )

    # ── 日志 ───────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    debug: bool = Field(default=False)


# 全局单例
settings = Settings()
