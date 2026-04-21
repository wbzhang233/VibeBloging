"""/agents — Agent 任务执行与状态查询."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from hermes_evo.agents.agent_pool import AgentPool
from hermes_evo.api.dependencies import get_agent_pool
from hermes_evo.api.schemas import (
    AgentExecuteBody,
    AgentExecuteResponse,
    PoolStatusResponse,
    TaskResultResponse,
)
from hermes_evo.models.agent import AgentTask

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/execute", response_model=AgentExecuteResponse, status_code=202)
async def execute_task(
    body: AgentExecuteBody,
    pool: AgentPool = Depends(get_agent_pool),
):
    """提交 Agent 任务（异步执行）."""
    task = AgentTask(
        instruction=body.instruction,
        context=body.context,
        max_iters=body.max_iters,
    )
    task_id = await pool.submit_task(task)
    return AgentExecuteResponse(task_id=task_id, status="submitted")


@router.get("/status", response_model=PoolStatusResponse)
async def get_pool_status(
    pool: AgentPool = Depends(get_agent_pool),
):
    """获取 Agent 池状态."""
    info = pool.get_pool_info()
    agents = [a.model_dump() for a in pool.get_status()]
    return PoolStatusResponse(
        pool_size=info["pool_size"],
        active_tasks=info["active_tasks"],
        total_submitted=info["total_submitted"],
        total_completed=info["total_completed"],
        agents=agents,
    )


@router.get("/tasks/{task_id}", response_model=TaskResultResponse)
async def get_task_result(
    task_id: str,
    pool: AgentPool = Depends(get_agent_pool),
):
    """获取任务执行结果."""
    result = pool.get_task_result(task_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task not found or still running: {task_id}",
        )
    return TaskResultResponse(
        task_id=result.task_id,
        agent_id=result.agent_id,
        success=result.success,
        result=result.result,
        tool_call_count=len(result.tool_calls),
        skills_created=result.skills_created,
        skills_patched=result.skills_patched,
        started_at=result.started_at,
        completed_at=result.completed_at,
    )
