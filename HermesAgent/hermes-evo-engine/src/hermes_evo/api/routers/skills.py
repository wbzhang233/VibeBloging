"""/skills — Skill CRUD + 热补丁 REST API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from hermes_evo.api.dependencies import get_skill_manager
from hermes_evo.api.schemas import (
    SkillCreateBody,
    SkillListResponse,
    SkillPatchBody,
    SkillResponse,
)
from hermes_evo.core.skill_manager import (
    AmbiguousPatchError,
    FrontmatterValidationError,
    PatchTargetNotFoundError,
    SizeLimitExceededError,
    SkillManager,
    SkillNotFoundError,
)
from hermes_evo.models.skill import SkillCreateRequest, SkillPatchRequest

router = APIRouter(prefix="/skills", tags=["skills"])


def _to_response(skill) -> SkillResponse:
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        content=skill.content,
        category=skill.category,
        version=skill.version,
        status=skill.status.value,
        safety_level=skill.safety_level,
        created_by=skill.created_by,
        tags=skill.tags,
        use_count=skill.use_count,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
        patch_count=len(skill.patch_history),
    )


@router.post("", response_model=SkillResponse, status_code=201)
async def create_skill(
    body: SkillCreateBody,
    sm: SkillManager = Depends(get_skill_manager),
):
    """创建新 Skill."""
    skill = await sm.create_skill(
        SkillCreateRequest(
            name=body.name,
            description=body.description,
            content=body.content,
            category=body.category,
            tags=body.tags,
            fallback_for_toolsets=body.fallback_for_toolsets,
            requires_tools=body.requires_tools,
            requires_toolsets=body.requires_toolsets,
            fallback_for_tools=body.fallback_for_tools,
        ),
        created_by="manual",
    )
    return _to_response(skill)


@router.get("", response_model=SkillListResponse)
async def list_skills(
    status: str | None = None,
    tag: str | None = None,
    safety_level: str | None = None,
    q: str | None = None,
    sm: SkillManager = Depends(get_skill_manager),
):
    """列出 Skill（支持过滤）."""
    skills = await sm.list_skills(
        status=status,
        tag=tag,
        safety_level=safety_level,
        query=q,
    )
    return SkillListResponse(
        total=len(skills),
        skills=[_to_response(s) for s in skills],
    )


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    sm: SkillManager = Depends(get_skill_manager),
):
    """获取 Skill 详情."""
    try:
        skill = await sm.get_skill(skill_id)
    except SkillNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    return _to_response(skill)


@router.patch("/{skill_id}", response_model=SkillResponse)
async def patch_skill(
    skill_id: str,
    body: SkillPatchBody,
    sm: SkillManager = Depends(get_skill_manager),
):
    """热补丁 — 就地修复 Skill 内容."""
    try:
        skill = await sm.patch_skill(
            skill_id,
            SkillPatchRequest(
                old_string=body.old_string,
                new_string=body.new_string,
                reason=body.reason,
            ),
            applied_by="api",
        )
    except SkillNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    except PatchTargetNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AmbiguousPatchError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(skill)


@router.delete("/{skill_id}", response_model=SkillResponse)
async def deprecate_skill(
    skill_id: str,
    sm: SkillManager = Depends(get_skill_manager),
):
    """软删除 — 标记为 deprecated（保留历史）."""
    try:
        skill = await sm.deprecate_skill(skill_id)
    except SkillNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    return _to_response(skill)


@router.get("/{skill_id}/patches")
async def get_patches(
    skill_id: str,
    sm: SkillManager = Depends(get_skill_manager),
):
    """获取 Skill 补丁历史."""
    try:
        skill = await sm.get_skill(skill_id)
    except SkillNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    return {
        "skill_id": skill.id,
        "name": skill.name,
        "version": skill.version,
        "patches": [p.model_dump(mode="json") for p in skill.patch_history],
    }
