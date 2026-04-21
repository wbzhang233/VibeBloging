"""FastAPI 应用工厂 + Lifespan 管理."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hermes_evo.agents.agent_pool import AgentPool
from hermes_evo.api.dependencies import init_services
from hermes_evo.api.routers import agents, metrics, review, skills
from hermes_evo.config import settings
from hermes_evo.core.dual_engine import DualEngineLearner
from hermes_evo.core.review_agent import ReviewAgent
from hermes_evo.core.skill_manager import SkillManager
from hermes_evo.core.skill_store import SkillStore
from hermes_evo.infra.database import close_db, init_db
from hermes_evo.infra.redis_client import close_redis

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理.

    启动时：初始化 DB、Redis、核心服务
    关闭时：清理连接
    """
    # ── 启动 ───────────────────────────────────────────────────────
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logger.info("Hermes Evo Engine starting...")

    # 初始化数据库
    await init_db()
    logger.info("Database initialized")

    # 模型配置
    model_config = {
        "model_name": settings.model_name,
        "api_key": settings.model_api_key,
        "api_url": settings.model_api_url,
    }

    # 初始化核心服务
    store = SkillStore()
    skill_manager = SkillManager(store=store)
    review_agent = ReviewAgent(model_config=model_config)
    dual_engine = DualEngineLearner(
        skill_manager=skill_manager,
        review_agent=review_agent,
    )
    agent_pool = AgentPool(
        skill_manager=skill_manager,
        dual_engine=dual_engine,
        model_config=model_config,
    )

    # 注册到依赖注入
    init_services(
        skill_manager=skill_manager,
        dual_engine=dual_engine,
        agent_pool=agent_pool,
        review_agent=review_agent,
    )
    logger.info("Core services initialized")

    yield

    # ── 关闭 ───────────────────────────────────────────────────────
    await close_redis()
    await close_db()
    logger.info("Hermes Evo Engine shutdown complete")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例."""
    app = FastAPI(
        title="HermesAgent Self-Evolution Engine",
        description=(
            "基于 AgentScope 的自进化智能体系统 — "
            "实现 Skill 自学习、热补丁自修复与条件激活。\n\n"
            "核心机制：双引擎学习（前台自觉 + 后台巡检）"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(skills.router)
    app.include_router(agents.router)
    app.include_router(review.router)
    app.include_router(metrics.router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    return app


# uvicorn 入口
app = create_app()
