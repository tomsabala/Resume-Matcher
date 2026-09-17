"""Switching which resume is the master.

Before this route a master could only be established by creating one — the
first upload, the wizard, or auto-promotion when the current one was stuck —
so a user who wanted a different base resume had to delete the one they had.
"""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _master(db: Any, workspace_id: str, title: str) -> str:
    resume = await db.create_resume_atomic_master(
        content=f"# {title}",
        content_type="md",
        processing_status="ready",
        title=title,
        workspace_id=workspace_id,
    )
    assert resume["is_master"] is True
    return str(resume["resume_id"])


async def _tailored(
    db: Any, workspace_id: str, parent_id: str, title: str, status: str = "ready"
) -> str:
    resume = await db.create_resume(
        content="{}",
        content_type="json",
        parent_id=parent_id,
        processing_status=status,
        title=title,
        workspace_id=workspace_id,
    )
    return str(resume["resume_id"])


async def test_promoting_a_resume_demotes_the_previous_master_and_keeps_it(
    isolated_db: Any,
) -> None:
    """The point of the feature: the old master is demoted, not destroyed. It
    has to come back in the ordinary list so it can be promoted again."""
    workspace_id = await isolated_db.default_workspace_id()
    old = await _master(isolated_db, workspace_id, "Uploaded CV")
    new = await _tailored(isolated_db, workspace_id, old, "Tailored for Acme")

    async with _client() as client:
        headers = {"X-Workspace-Id": workspace_id}
        promoted = await client.post(f"/api/v1/resumes/{new}/master", headers=headers)
        listed = await client.get("/api/v1/resumes/list", headers=headers)
        fetched_new = await client.get(f"/api/v1/resumes?resume_id={new}")
        fetched_old = await client.get(f"/api/v1/resumes?resume_id={old}")

    assert promoted.status_code == 200, promoted.text
    assert promoted.json() == {
        "resume_id": new,
        "is_master": True,
        "previous_master_id": old,
    }
    assert (await isolated_db.get_master_resume(workspace_id))["resume_id"] == new
    # The demoted one is an ordinary resume now, so the list (which hides only
    # the master) is exactly where it must show up.
    assert [row["resume_id"] for row in listed.json()["data"]] == [old]
    assert fetched_new.json()["data"]["is_master"] is True
    assert fetched_old.json()["data"]["is_master"] is False


async def test_a_promoted_tailored_resume_keeps_its_lineage(isolated_db: Any) -> None:
    """``parent_id`` gates the cover-letter, outreach, interview-prep and
    job-description routes. Clearing it on promotion would silently take those
    away from the resume the user just chose to build on."""
    workspace_id = await isolated_db.default_workspace_id()
    old = await _master(isolated_db, workspace_id, "Uploaded CV")
    new = await _tailored(isolated_db, workspace_id, old, "Tailored for Acme")

    async with _client() as client:
        await client.post(
            f"/api/v1/resumes/{new}/master", headers={"X-Workspace-Id": workspace_id}
        )
        fetched = await client.get(f"/api/v1/resumes?resume_id={new}")

    assert fetched.json()["data"]["parent_id"] == old


async def test_promoting_the_current_master_changes_nothing(isolated_db: Any) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    current = await _master(isolated_db, workspace_id, "Uploaded CV")

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{current}/master",
            headers={"X-Workspace-Id": workspace_id},
        )

    assert response.status_code == 200, response.text
    assert response.json()["previous_master_id"] is None
    assert (await isolated_db.get_master_resume(workspace_id))["resume_id"] == current


@pytest.mark.parametrize("status", ["pending", "processing", "failed"])
async def test_an_unready_resume_cannot_become_the_master(
    isolated_db: Any, status: str
) -> None:
    """A master that is not ready puts the workspace into `setup_required` and
    disables tailoring, so the route refuses instead of breaking it."""
    workspace_id = await isolated_db.default_workspace_id()
    current = await _master(isolated_db, workspace_id, "Uploaded CV")
    unready = await _tailored(isolated_db, workspace_id, current, "Half done", status)

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{unready}/master",
            headers={"X-Workspace-Id": workspace_id},
        )

    assert response.status_code == 409, response.text
    assert (await isolated_db.get_master_resume(workspace_id))["resume_id"] == current


async def test_a_resume_from_another_workspace_is_not_found(isolated_db: Any) -> None:
    """``get_resume`` is not workspace-scoped and ``set_master_resume`` takes
    its scope from the target row, so a leaked id would otherwise promote a
    master inside a workspace the request never named."""
    default_id = await isolated_db.default_workspace_id()
    async with _client() as client:
        other = (await client.post("/api/v1/workspaces", json={"name": "Lior"})).json()[
            "workspace_id"
        ]

    default_master = await _master(isolated_db, default_id, "Tom")
    other_master = await _master(isolated_db, other, "Lior")
    stranger = await _tailored(isolated_db, other, other_master, "Lior tailored")

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{stranger}/master", headers={"X-Workspace-Id": default_id}
        )

    assert response.status_code == 404
    assert (await isolated_db.get_master_resume(default_id))["resume_id"] == default_master
    assert (await isolated_db.get_master_resume(other))["resume_id"] == other_master


async def test_a_missing_resume_is_a_404(isolated_db: Any) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    async with _client() as client:
        response = await client.post(
            "/api/v1/resumes/missing/master", headers={"X-Workspace-Id": workspace_id}
        )

    assert response.status_code == 404
