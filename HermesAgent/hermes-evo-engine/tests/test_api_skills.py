"""FastAPI Skills API 端点测试."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hermes_evo.api.app import create_app
from hermes_evo.api.dependencies import init_services
from hermes_evo.core.conditional_activation import ConditionalActivator
from hermes_evo.core.safety_scanner import SafetyScanner
from hermes_evo.core.skill_manager import SkillManager


# 复用 test_skill_manager 中的内存 Store
class InMemorySkillStore:
    def __init__(self):
        self._skills = {}

    async def save(self, skill):
        self._skills[skill.id] = skill

    async def update(self, skill):
        self._skills[skill.id] = skill

    async def get(self, skill_id):
        return self._skills.get(skill_id)

    async def get_by_name(self, name):
        for s in self._skills.values():
            if s.name == name:
                return s
        return None

    async def list_all(self, status=None, tag=None, safety_level=None, query=None):
        results = list(self._skills.values())
        if status:
            results = [s for s in results if s.status.value == status]
        if query:
            results = [s for s in results if query.lower() in s.name.lower()]
        return results

    def _write_file(self, skill):
        pass


class MockDualEngine:
    pass


class MockAgentPool:
    def get_pool_info(self):
        return {"pool_size": 5, "active_tasks": 0, "total_submitted": 0, "total_completed": 0, "agents": 0}

    def get_status(self):
        return []


class MockReviewAgent:
    pass


@pytest.fixture
def client():
    app = create_app()
    store = InMemorySkillStore()
    sm = SkillManager(store=store, scanner=SafetyScanner(), activator=ConditionalActivator())
    init_services(
        skill_manager=sm,
        dual_engine=MockDualEngine(),
        agent_pool=MockAgentPool(),
        review_agent=MockReviewAgent(),
    )
    return TestClient(app)


class TestSkillsAPI:
    """Skills REST API 集成测试."""

    def test_create_skill(self, client):
        resp = client.post("/skills", json={
            "name": "api-test-skill",
            "description": "Created via API",
            "content": "Step 1: Test",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "api-test-skill"
        assert data["version"] == 1
        assert data["safety_level"] == "safe"

    def test_list_skills(self, client):
        client.post("/skills", json={"name": "s1", "description": "d", "content": "c"})
        client.post("/skills", json={"name": "s2", "description": "d", "content": "c"})
        resp = client.get("/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_get_skill(self, client):
        create_resp = client.post("/skills", json={
            "name": "get-test",
            "description": "d",
            "content": "c",
        })
        skill_id = create_resp.json()["id"]
        resp = client.get(f"/skills/{skill_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "get-test"

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/skills/nonexistent-id")
        assert resp.status_code == 404

    def test_patch_skill(self, client):
        create_resp = client.post("/skills", json={
            "name": "patch-test",
            "description": "d",
            "content": "Use https://old.example.com for API",
        })
        skill_id = create_resp.json()["id"]
        resp = client.patch(f"/skills/{skill_id}", json={
            "old_string": "https://old.example.com",
            "new_string": "https://new.example.com",
            "reason": "URL migrated",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 2
        assert data["patch_count"] == 1

    def test_deprecate_skill(self, client):
        create_resp = client.post("/skills", json={
            "name": "dep-test",
            "description": "d",
            "content": "c",
        })
        skill_id = create_resp.json()["id"]
        resp = client.delete(f"/skills/{skill_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deprecated"

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_metrics_endpoint(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_skills" in data
        assert "pool_info" in data
