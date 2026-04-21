"""Async SQLAlchemy — TDSQL (MySQL 兼容) 连接与会话管理."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy import JSON
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from hermes_evo.config import settings

# ── Engine & Session ───────────────────────────────────────────────────
# TDSQL 使用 MySQL 协议，驱动为 aiomysql

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """提供一个 async session 上下文管理器."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── ORM Base ───────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """ORM 基类."""


# ── Skill ORM 模型 ─────────────────────────────────────────────────────
# 注: TDSQL (MySQL) 不支持 JSONB，使用 JSON 类型替代


class SkillRecord(Base):
    """skills 表 ORM 映射."""

    __tablename__ = "skills"

    id = Column(String(36), primary_key=True)
    name = Column(String(256), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False, default="")
    content = Column(Text, nullable=False, default="")
    category = Column(String(100), nullable=False, default="")
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by = Column(String(50), nullable=False, default="manual")
    tags = Column(JSON, nullable=False, default=list)
    fallback_for_toolsets = Column(JSON, nullable=False, default=list)
    requires_tools = Column(JSON, nullable=False, default=list)
    requires_toolsets = Column(JSON, nullable=False, default=list)
    fallback_for_tools = Column(JSON, nullable=False, default=list)
    safety_level = Column(String(20), nullable=False, default="safe")
    use_count = Column(Integer, nullable=False, default=0)
    patch_history = Column(JSON, nullable=False, default=list)


class ExecutionRecordDB(Base):
    """execution_records 表 ORM 映射."""

    __tablename__ = "execution_records"

    task_id = Column(String(36), primary_key=True)
    agent_id = Column(String(128), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    tool_calls = Column(JSON, nullable=False, default=list)
    skills_created = Column(JSON, nullable=False, default=list)
    skills_patched = Column(JSON, nullable=False, default=list)
    result = Column(Text, nullable=False, default="")
    success = Column(Integer, nullable=False, default=0)


class ReviewRecordDB(Base):
    """review_records 表 ORM 映射."""

    __tablename__ = "review_records"

    review_id = Column(String(36), primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    conversation_window = Column(Integer, nullable=False, default=0)
    candidates = Column(JSON, nullable=False, default=list)
    nothing_to_save = Column(Integer, nullable=False, default=0)
    reasoning = Column(Text, nullable=False, default="")


# ── 数据库初始化 ───────────────────────────────────────────────────────


async def init_db() -> None:
    """创建所有表（开发环境使用，生产用 Alembic）."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """关闭数据库引擎."""
    await engine.dispose()
