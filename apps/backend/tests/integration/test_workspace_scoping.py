"""Workspace scoping: two workspaces are independent document namespaces."""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _create_master(db: Any, workspace_id: str, title: str) -> str:
    """Create a ready master resume inside ``workspace_id``."""
    resume = await db.create_resume_atomic_master(
        content=f"# {title}",
        content_type="md",
        filename=f"{title}.md",
        processing_status="ready",
        title=title,
        workspace_id=workspace_id,
    )
    assert resume["is_master"] is True
    return str(resume["resume_id"])


async def test_two_workspaces_hold_their_own_master_resume(isolated_db: Any) -> None:
    async with await _client() as client:
        created = await client.post("/api/v1/workspaces", json={"name": "Lior"})
        assert created.status_code == 201
        lior = created.json()["workspace_id"]

    default_id = await isolated_db.default_workspace_id()
    assert lior != default_id

    default_master = await _create_master(isolated_db, default_id, "Tom")
    lior_master = await _create_master(isolated_db, lior, "Lior")

    masters = await isolated_db.list_resumes(default_id)
    assert [row["resume_id"] for row in masters] == [default_master]
    masters = await isolated_db.list_resumes(lior)
    assert [row["resume_id"] for row in masters] == [lior_master]

    # The pre-workspace schema had a database-global unique index here, which
    # made a second master impossible.
    assert (await isolated_db.get_master_resume(default_id))["resume_id"] == default_master
    assert (await isolated_db.get_master_resume(lior))["resume_id"] == lior_master


async def test_resume_list_is_disjoint_per_workspace_header(isolated_db: Any) -> None:
    async with await _client() as client:
        lior = (await client.post("/api/v1/workspaces", json={"name": "Lior"})).json()[
            "workspace_id"
        ]
        default_id = await isolated_db.default_workspace_id()

        await isolated_db.create_resume(
            content="{}", content_type="json", title="Default CV", workspace_id=default_id
        )
        await isolated_db.create_resume(
            content="{}", content_type="json", title="Lior CV", workspace_id=lior
        )

        default_list = await client.get(
            "/api/v1/resumes/list", headers={"X-Workspace-Id": default_id}
        )
        lior_list = await client.get(
            "/api/v1/resumes/list", headers={"X-Workspace-Id": lior}
        )

    default_titles = {row["title"] for row in default_list.json()["data"]}
    lior_titles = {row["title"] for row in lior_list.json()["data"]}
    assert default_titles == {"Default CV"}
    assert lior_titles == {"Lior CV"}


async def test_unknown_workspace_header_falls_back_to_default(isolated_db: Any) -> None:
    """The print route and stale localStorage ids must not 404."""
    default_id = await isolated_db.default_workspace_id()
    await isolated_db.create_resume(
        content="{}", content_type="json", title="Default CV", workspace_id=default_id
    )
    async with await _client() as client:
        response = await client.get(
            "/api/v1/resumes/list", headers={"X-Workspace-Id": "does-not-exist"}
        )
    assert [row["title"] for row in response.json()["data"]] == ["Default CV"]


async def test_tracker_board_is_workspace_scoped(isolated_db: Any) -> None:
    async with await _client() as client:
        lior = (await client.post("/api/v1/workspaces", json={"name": "Lior"})).json()[
            "workspace_id"
        ]
        default_id = await isolated_db.default_workspace_id()
        for workspace_id, company in ((default_id, "Acme"), (lior, "Globex")):
            resume = await isolated_db.create_resume(
                content="{}", content_type="json", workspace_id=workspace_id
            )
            await isolated_db.create_manual_application(
                content=f"{company} is hiring",
                resume_id=resume["resume_id"],
                company=company,
                workspace_id=workspace_id,
            )

        default_board = (
            await client.get(
                "/api/v1/applications", headers={"X-Workspace-Id": default_id}
            )
        ).json()
        lior_board = (
            await client.get("/api/v1/applications", headers={"X-Workspace-Id": lior})
        ).json()

    assert [card["company"] for card in default_board["columns"]["applied"]] == ["Acme"]
    assert [card["company"] for card in lior_board["columns"]["applied"]] == ["Globex"]


async def test_default_workspace_cannot_be_deleted(isolated_db: Any) -> None:
    default_id = await isolated_db.default_workspace_id()
    async with await _client() as client:
        conflict = await client.delete(f"/api/v1/workspaces/{default_id}")
        assert conflict.status_code == 409

        lior = (await client.post("/api/v1/workspaces", json={"name": "Lior"})).json()[
            "workspace_id"
        ]
        assert (await client.delete(f"/api/v1/workspaces/{lior}")).status_code == 200
    assert await isolated_db.get_workspace(lior) is None


async def test_deleting_a_workspace_removes_its_documents(isolated_db: Any) -> None:
    async with await _client() as client:
        lior = (await client.post("/api/v1/workspaces", json={"name": "Lior"})).json()[
            "workspace_id"
        ]
        resume = await isolated_db.create_resume(
            content="{}",
            content_type="json",
            processed_data={"schemaVersion": 2, "header": {}, "sections": []},
            workspace_id=lior,
        )
        version = await isolated_db.seed_resume_version(
            resume["resume_id"], workspace_id=lior, origin="upload"
        )
        job = await isolated_db.create_job("jd text", workspace_id=lior)
        await client.delete(f"/api/v1/workspaces/{lior}")

    assert await isolated_db.get_resume(resume["resume_id"], workspace_id=lior) is None
    assert await isolated_db.get_job(job["job_id"], workspace_id=lior) is None
    # The version history is the bulk of a purged tenant's data; leaving it
    # behind would outlive the workspace it belonged to.
    assert (
        await isolated_db.get_resume_version(version["version_id"], workspace_id=lior)
        is None
    )


async def test_workspace_slugs_are_deduplicated(isolated_db: Any) -> None:
    async with await _client() as client:
        first = (await client.post("/api/v1/workspaces", json={"name": "Tom Bar"})).json()
        second = (await client.post("/api/v1/workspaces", json={"name": "Tom  bar!"})).json()
    assert first["slug"] == "tom-bar"
    assert second["slug"] == "tom-bar-2"


async def test_promoting_a_default_demotes_the_previous_one(isolated_db: Any) -> None:
    default_id = await isolated_db.default_workspace_id()
    async with await _client() as client:
        lior = (await client.post("/api/v1/workspaces", json={"name": "Lior"})).json()[
            "workspace_id"
        ]
        promoted = await client.patch(
            f"/api/v1/workspaces/{lior}", json={"is_default": True}
        )
    assert promoted.json()["is_default"] is True
    assert (await isolated_db.get_workspace(default_id))["is_default"] is False
    assert await isolated_db.default_workspace_id() == lior
