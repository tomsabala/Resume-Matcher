"""Cross-tenant denial: in header mode, no tenant can reach another's data.

Every test here drives the real ASGI app with gateway headers, so it exercises
``TenantMiddleware``, the ``WorkspaceId`` dependency and the scoped facade
together — the three layers that have to agree for the boundary to hold.

The shape is always the same, and it is deliberately the shape a reviewer
looks for:

* **B reading A's id → 404.** Not 403: a tenant must not learn that another's
  row exists.
* **B writing A's id → 404, and A's row byte-identical afterwards.**
* **B's list → only B's rows.**
"""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration

TENANT_A = "anon-aaaa000000000000"
TENANT_B = "anon-bbbb000000000000"
ADMIN = "admin-cccc000000000000"


@pytest.fixture(autouse=True)
def header_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run these tests the way the shared deployment runs.

    The tenant cache is cleared per test by the root ``isolated_backend_state``
    fixture, so each test resolves its own fresh workspaces.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "tenant_mode", "header")


def _client(tenant: str | None = None, role: str = "anon", **extra: str) -> AsyncClient:
    headers = dict(extra)
    if tenant is not None:
        headers["X-Apps-Tenant"] = tenant
        headers["X-Apps-Role"] = role
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    )


async def _workspace_of(tenant: str, role: str = "anon") -> str:
    """The workspace the middleware resolves for a tenant, creating it."""
    async with _client(tenant, role) as client:
        response = await client.get("/api/v1/workspaces")
        assert response.status_code == 200, response.text
        workspaces = response.json()["workspaces"]
        assert len(workspaces) == 1
        return str(workspaces[0]["workspace_id"])


async def _ready_resume(db: Any, workspace_id: str, title: str) -> str:
    resume = await db.create_resume(
        content="{}",
        content_type="json",
        title=title,
        processing_status="ready",
        processed_data={"schemaVersion": 2, "header": {}, "sections": []},
        workspace_id=workspace_id,
    )
    return str(resume["resume_id"])


# -- the middleware boundary ------------------------------------------------


async def test_a_request_without_a_tenant_is_not_found(isolated_db: Any) -> None:
    """The gateway always injects a tenant, so its absence means the proxy was
    bypassed. Answer 404 rather than serving the default workspace."""
    async with _client() as client:
        response = await client.get("/api/v1/resumes/list")
    assert response.status_code == 404


async def test_the_healthcheck_answers_without_a_tenant(isolated_db: Any) -> None:
    """The container healthcheck cannot present gateway headers."""
    async with _client() as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


async def test_a_blank_tenant_header_is_not_found(isolated_db: Any) -> None:
    async with _client() as client:
        response = await client.get(
            "/api/v1/resumes/list", headers={"X-Apps-Tenant": "   "}
        )
    assert response.status_code == 404


async def test_each_tenant_gets_its_own_fresh_workspace(isolated_db: Any) -> None:
    first = await _workspace_of(TENANT_A)
    second = await _workspace_of(TENANT_B)
    assert first != second

    async with _client(TENANT_B) as client:
        listed = (await client.get("/api/v1/workspaces")).json()["workspaces"]
    assert [row["workspace_id"] for row in listed] == [second]


async def test_the_first_admin_request_claims_the_existing_data(
    isolated_db: Any,
) -> None:
    """A standalone instance flipped to header mode must not orphan its data.

    The default workspace the schema seeds carries ``tenant_ref = ""``; the
    first ``admin`` request adopts it, resumes and all.
    """
    default_id = await isolated_db.default_workspace_id()
    resume_id = await _ready_resume(isolated_db, default_id, "Existing CV")

    async with _client(ADMIN, role="admin") as client:
        workspaces = (await client.get("/api/v1/workspaces")).json()["workspaces"]
        assert [row["workspace_id"] for row in workspaces] == [default_id]
        listed = (await client.get("/api/v1/resumes/list")).json()["data"]
    assert [row["resume_id"] for row in listed] == [resume_id]

    # An anonymous visitor arriving afterwards gets nothing of the admin's.
    async with _client(TENANT_B) as client:
        listed = (await client.get("/api/v1/resumes/list")).json()["data"]
    assert listed == []


async def test_an_anonymous_request_never_claims_existing_data(
    isolated_db: Any,
) -> None:
    default_id = await isolated_db.default_workspace_id()
    await _ready_resume(isolated_db, default_id, "Existing CV")

    anonymous_workspace = await _workspace_of(TENANT_A)
    assert anonymous_workspace != default_id
    async with _client(TENANT_A) as client:
        assert (await client.get("/api/v1/resumes/list")).json()["data"] == []


async def test_a_foreign_workspace_header_falls_back_to_the_callers_own(
    isolated_db: Any,
) -> None:
    """``X-Workspace-Id`` is browser localStorage and outlives a tenant.

    Naming someone else's workspace degrades to the caller's own default
    rather than 404-ing, and must never widen what the caller can see.
    """
    workspace_a = await _workspace_of(TENANT_A)
    workspace_b = await _workspace_of(TENANT_B)
    await _ready_resume(isolated_db, workspace_a, "A's CV")
    b_resume = await _ready_resume(isolated_db, workspace_b, "B's CV")

    async with _client(TENANT_B, **{"X-Workspace-Id": workspace_a}) as client:
        listed = (await client.get("/api/v1/resumes/list")).json()["data"]
    assert [row["resume_id"] for row in listed] == [b_resume]


# -- documents --------------------------------------------------------------


async def test_reading_another_tenants_resume_is_not_found(isolated_db: Any) -> None:
    workspace_a = await _workspace_of(TENANT_A)
    await _workspace_of(TENANT_B)
    resume_id = await _ready_resume(isolated_db, workspace_a, "A's CV")

    async with _client(TENANT_B) as client:
        assert (
            await client.get(f"/api/v1/resumes?resume_id={resume_id}")
        ).status_code == 404
        assert (await client.get(f"/api/v1/resumes/{resume_id}/pdf")).status_code == 404
        assert (await client.get(f"/api/v1/resumes/{resume_id}/tex")).status_code == 404
        assert (
            await client.get(f"/api/v1/resumes/{resume_id}/versions")
        ).status_code == 404


async def test_writing_another_tenants_resume_leaves_it_untouched(
    isolated_db: Any,
) -> None:
    workspace_a = await _workspace_of(TENANT_A)
    await _workspace_of(TENANT_B)
    resume_id = await _ready_resume(isolated_db, workspace_a, "A's CV")
    before = await isolated_db.get_resume(resume_id, workspace_id=workspace_a)

    async with _client(TENANT_B) as client:
        assert (
            await client.patch(
                f"/api/v1/resumes/{resume_id}/title", json={"title": "Stolen"}
            )
        ).status_code == 404
        assert (
            await client.post(f"/api/v1/resumes/{resume_id}/master")
        ).status_code == 404
        assert (
            await client.delete(f"/api/v1/resumes/{resume_id}")
        ).status_code == 404

    after = await isolated_db.get_resume(resume_id, workspace_id=workspace_a)
    assert after == before


async def test_reading_another_tenants_version_is_not_found(isolated_db: Any) -> None:
    workspace_a = await _workspace_of(TENANT_A)
    await _workspace_of(TENANT_B)
    resume_id = await _ready_resume(isolated_db, workspace_a, "A's CV")
    version = await isolated_db.seed_resume_version(
        resume_id, workspace_id=workspace_a, origin="import"
    )
    assert version is not None

    async with _client(TENANT_B) as client:
        assert (
            await client.get(f"/api/v1/versions/{version['version_id']}")
        ).status_code == 404
        assert (
            await client.patch(
                f"/api/v1/versions/{version['version_id']}", json={"label": "mine"}
            )
        ).status_code == 404

    unchanged = await isolated_db.get_resume_version(
        version["version_id"], workspace_id=workspace_a
    )
    assert unchanged is not None and unchanged["label"] is None


async def test_reading_another_tenants_job_is_not_found(isolated_db: Any) -> None:
    workspace_a = await _workspace_of(TENANT_A)
    await _workspace_of(TENANT_B)
    job = await isolated_db.create_job(content="A's JD", workspace_id=workspace_a)

    async with _client(TENANT_B) as client:
        assert (await client.get(f"/api/v1/jobs/{job['job_id']}")).status_code == 404


# -- tracker ----------------------------------------------------------------


async def test_another_tenants_tracker_card_is_unreachable(isolated_db: Any) -> None:
    workspace_a = await _workspace_of(TENANT_A)
    await _workspace_of(TENANT_B)
    resume_id = await _ready_resume(isolated_db, workspace_a, "A's CV")
    job = await isolated_db.create_job(content="A's JD", workspace_id=workspace_a)
    card = await isolated_db.create_application(
        job_id=job["job_id"], resume_id=resume_id, workspace_id=workspace_a
    )
    card_id = card["application_id"]

    async with _client(TENANT_B) as client:
        assert (
            await client.get(f"/api/v1/applications/{card_id}")
        ).status_code == 404
        assert (
            await client.patch(
                f"/api/v1/applications/{card_id}", json={"notes": "stolen"}
            )
        ).status_code == 404
        # Bulk operations skip foreign ids instead of failing the batch, so the
        # assertion is that nothing was affected.
        bulk = await client.post(
            "/api/v1/applications/bulk-delete", json={"application_ids": [card_id]}
        )
        assert bulk.status_code == 200 and bulk.json()["affected"] == 0
        assert (await client.get("/api/v1/applications")).json()["columns"][
            "applied"
        ] == []

    survivor = await isolated_db.get_application(card_id, workspace_id=workspace_a)
    assert survivor is not None and survivor["notes"] != "stolen"


# -- settings, keys and reset ----------------------------------------------


async def test_api_keys_are_per_tenant(isolated_db: Any) -> None:
    await _workspace_of(TENANT_A)
    await _workspace_of(TENANT_B)

    async with _client(TENANT_B) as client:
        saved = await client.post("/api/v1/config/api-keys", json={"openai": "sk-b"})
        assert saved.status_code == 200
        providers = (await client.get("/api/v1/config/api-keys")).json()["providers"]
        assert next(p for p in providers if p["provider"] == "openai")["configured"]

    async with _client(TENANT_A) as client:
        providers = (await client.get("/api/v1/config/api-keys")).json()["providers"]
    assert not next(p for p in providers if p["provider"] == "openai")["configured"]


async def test_clearing_keys_only_clears_the_callers(isolated_db: Any) -> None:
    await _workspace_of(TENANT_A)
    await _workspace_of(TENANT_B)
    async with _client(TENANT_A) as client:
        await client.post("/api/v1/config/api-keys", json={"openai": "sk-a"})
    async with _client(TENANT_B) as client:
        await client.post("/api/v1/config/api-keys", json={"openai": "sk-b"})
        cleared = await client.delete(
            "/api/v1/config/api-keys?confirm=CLEAR_ALL_KEYS"
        )
        assert cleared.status_code == 200

    async with _client(TENANT_A) as client:
        providers = (await client.get("/api/v1/config/api-keys")).json()["providers"]
    assert next(p for p in providers if p["provider"] == "openai")["configured"]


async def test_prompt_overrides_are_per_tenant(isolated_db: Any) -> None:
    await _workspace_of(TENANT_A)
    await _workspace_of(TENANT_B)

    async with _client(TENANT_B) as client:
        updated = await client.put(
            "/api/v1/config/prompts", json={"default_prompt_id": "full"}
        )
        assert updated.status_code == 200
        assert updated.json()["default_prompt_id"] == "full"

    async with _client(TENANT_A) as client:
        mine = (await client.get("/api/v1/config/prompts")).json()
    assert mine["default_prompt_id"] == "keywords"


async def test_feature_overrides_are_per_tenant(isolated_db: Any) -> None:
    await _workspace_of(TENANT_A)
    await _workspace_of(TENANT_B)

    async with _client(TENANT_B) as client:
        assert (
            await client.put(
                "/api/v1/config/features", json={"enable_cover_letter": True}
            )
        ).status_code == 200

    async with _client(TENANT_A) as client:
        features = (await client.get("/api/v1/config/features")).json()
    assert features["enable_cover_letter"] is False


async def test_reset_only_empties_the_callers_workspace(isolated_db: Any) -> None:
    workspace_a = await _workspace_of(TENANT_A)
    workspace_b = await _workspace_of(TENANT_B)
    a_resume = await _ready_resume(isolated_db, workspace_a, "A's CV")
    await _ready_resume(isolated_db, workspace_b, "B's CV")

    async with _client(TENANT_B) as client:
        reset = await client.post(
            "/api/v1/config/reset", json={"confirm": "RESET_ALL_DATA"}
        )
        assert reset.status_code == 200
        assert (await client.get("/api/v1/resumes/list")).json()["data"] == []

    async with _client(TENANT_A) as client:
        listed = (await client.get("/api/v1/resumes/list")).json()["data"]
    assert [row["resume_id"] for row in listed] == [a_resume]


async def test_status_counts_only_the_callers_rows(isolated_db: Any) -> None:
    workspace_a = await _workspace_of(TENANT_A)
    await _workspace_of(TENANT_B)
    await _ready_resume(isolated_db, workspace_a, "A's CV")

    async with _client(TENANT_B) as client:
        status = (await client.get("/api/v1/status")).json()
    assert status["database_stats"]["total_resumes"] == 0
    assert status["has_master_resume"] is False


# -- the operator's own LLM_API_KEY ----------------------------------------


async def test_an_anonymous_visitor_is_never_shown_the_instance_key(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /config/llm-api-key`` masked whatever ``resolve_api_key`` returned.

    With the env fallback ungated, that mask was built from the operator's
    ``LLM_API_KEY`` — handing an anonymous visitor its first and last four
    characters, on an endpoint that needs no key of their own to reach.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "sk-operator-secret-value")
    await _workspace_of(TENANT_A)

    async with _client(TENANT_A) as client:
        response = await client.get("/api/v1/config/llm-api-key")

    assert response.status_code == 200
    assert response.json()["api_key"] == ""
    assert "sk-o" not in response.text
    assert "alue" not in response.text


async def test_an_anonymous_visitor_cannot_spend_the_instance_key(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no key of their own they get "not configured", not the operator's."""
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "sk-operator-secret-value")
    await _workspace_of(TENANT_A)

    async with _client(TENANT_A) as client:
        response = await client.post("/api/v1/config/llm-test", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["healthy"] is False
    assert body["error_code"] == "api_key_missing"
    assert "sk-operator" not in response.text


async def test_the_admin_still_gets_the_instance_key(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate is on the role, not on header mode: the operator keeps their key."""
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "sk-operator-secret-value")

    async with _client(ADMIN, role="admin") as client:
        response = await client.get("/api/v1/config/llm-api-key")

    assert response.status_code == 200
    # Masked, but present — first and last four are the endpoint's contract.
    assert response.json()["api_key"].startswith("sk-o")
    assert response.json()["api_key"].endswith("alue")


async def test_a_tenants_own_key_is_the_one_it_sees(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "sk-operator-secret-value")
    await _workspace_of(TENANT_A)

    async with _client(TENANT_A) as client:
        assert (
            await client.post(
                "/api/v1/config/api-keys", json={"openai": "sk-tenant-a-own-key"}
            )
        ).status_code == 200
        shown = (await client.get("/api/v1/config/llm-api-key")).json()["api_key"]

    assert shown.startswith("sk-t") and shown.endswith("-key")
    assert "operator" not in shown


# -- workspaces (the tenant-level router) ----------------------------------


async def test_another_tenants_workspace_cannot_be_renamed_or_deleted(
    isolated_db: Any,
) -> None:
    workspace_a = await _workspace_of(TENANT_A)
    await _workspace_of(TENANT_B)

    async with _client(TENANT_B) as client:
        assert (
            await client.patch(
                f"/api/v1/workspaces/{workspace_a}", json={"name": "Stolen"}
            )
        ).status_code == 404
        assert (
            await client.delete(f"/api/v1/workspaces/{workspace_a}")
        ).status_code == 404

    unchanged = await isolated_db.get_workspace(workspace_a)
    assert unchanged is not None and unchanged["name"] != "Stolen"


async def test_a_tenant_keeps_multiple_profiles(isolated_db: Any) -> None:
    """Tenant → workspaces stays one-to-many: the profile switcher survives."""
    await _workspace_of(TENANT_A)
    async with _client(TENANT_A) as client:
        created = await client.post("/api/v1/workspaces", json={"name": "Hebrew CV"})
        assert created.status_code == 201
        second = created.json()["workspace_id"]
        listed = (await client.get("/api/v1/workspaces")).json()["workspaces"]
    assert second in {row["workspace_id"] for row in listed}
    assert len(listed) == 2

    async with _client(TENANT_B) as client:
        assert (await client.get("/api/v1/workspaces")).json()["workspaces"] != listed
