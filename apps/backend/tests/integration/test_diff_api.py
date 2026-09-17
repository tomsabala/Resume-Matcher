"""The comparison endpoint: ref resolution, scoping and partial accept."""

import copy
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

from tests.integration.test_dynamic_sections_api import owner_document

pytestmark = pytest.mark.integration


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _resume(db: Any, workspace_id: str | None = None) -> str:
    scope = workspace_id or await db.default_workspace_id()
    resume = await db.create_resume(
        content="{}",
        content_type="json",
        processed_data=owner_document(),
        workspace_id=scope,
    )
    await db.seed_resume_version(
        resume["resume_id"], workspace_id=scope, origin="import"
    )
    return str(resume["resume_id"])


async def test_two_versions_of_one_resume_compare(isolated_db: Any) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _resume(isolated_db)
    original = (
        await isolated_db.list_resume_versions(resume_id, workspace_id=workspace_id)
    )[0]

    edited = copy.deepcopy(owner_document())
    edited["sections"][0]["heading"] = "Profile"
    head = await isolated_db.commit_resume_version(
        resume_id, edited, workspace_id=workspace_id, origin="manual"
    )

    async with await _client() as client:
        response = await client.post(
            "/api/v1/diff",
            json={
                "base": {"version_id": original["version_id"]},
                "head": {"version_id": head["version_id"]},
                "context": 0,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    renamed = [s for s in body["sections"] if s["status"] == "renamed"]
    assert [(s["base_heading"], s["head_heading"]) for s in renamed] == [
        ("About Me", "Profile")
    ]
    assert body["stats"]["total_changes"] == 1


async def test_a_resume_ref_resolves_to_its_current_content(isolated_db: Any) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    first = await _resume(isolated_db)
    second = await _resume(isolated_db)
    edited = copy.deepcopy(owner_document())
    edited["sections"][0]["text"] = "A different engineer."
    await isolated_db.commit_resume_version(
        second, edited, workspace_id=workspace_id, origin="manual"
    )

    async with await _client() as client:
        response = await client.post(
            "/api/v1/diff",
            json={"base": {"resume_id": first}, "head": {"resume_id": second}, "context": 0},
        )

    body = response.json()
    modified = [
        row
        for section in body["sections"]
        for row in section["rows"]
        if row["status"] == "modified"
    ]
    assert [row["head_text"] for row in modified] == ["A different engineer."]


@pytest.mark.parametrize(
    "ref", [{}, {"resume_id": "a", "version_id": "b"}], ids=["neither", "both"]
)
async def test_a_ref_must_name_exactly_one_thing(
    isolated_db: Any, ref: dict[str, str]
) -> None:
    resume_id = await _resume(isolated_db)
    async with await _client() as client:
        response = await client.post(
            "/api/v1/diff", json={"base": ref, "head": {"resume_id": resume_id}}
        )
    assert response.status_code == 422


async def test_a_cross_workspace_ref_is_not_found(isolated_db: Any) -> None:
    """Workspaces are separate namespaces; a diff reads two documents at once.

    404, not 403: the scoped read cannot tell an id that belongs to another
    workspace from one that does not exist, and must not confirm it does.
    """
    default_id = await isolated_db.default_workspace_id()
    other = await isolated_db.create_workspace(name="Lior")
    mine = await _resume(isolated_db, default_id)
    theirs = await _resume(isolated_db, other["workspace_id"])

    async with await _client() as client:
        response = await client.post(
            "/api/v1/diff",
            json={"base": {"resume_id": mine}, "head": {"resume_id": theirs}},
            headers={"X-Workspace-Id": default_id},
        )

    assert response.status_code == 404


async def test_an_unknown_ref_is_a_404(isolated_db: Any) -> None:
    resume_id = await _resume(isolated_db)
    async with await _client() as client:
        response = await client.post(
            "/api/v1/diff",
            json={
                "base": {"resume_id": resume_id},
                "head": {"version_id": "does-not-exist"},
            },
        )
    assert response.status_code == 404


async def test_tex_mode_compares_generated_sources_when_neither_side_is_overridden(
    isolated_db: Any,
) -> None:
    """Without a saved override a resume still has LaTeX — the one its
    document generates. Treating that as "" would report the whole file as
    added."""
    base_doc = owner_document()
    head_doc = copy.deepcopy(base_doc)
    head_doc["header"]["headline"] = "Distributed Systems Engineer"

    workspace_id = await isolated_db.default_workspace_id()
    base = await isolated_db.create_resume(
        content="{}", content_type="document", processed_data=base_doc,
        processing_status="ready", workspace_id=workspace_id,
    )
    head = await isolated_db.create_resume(
        content="{}", content_type="document", processed_data=head_doc,
        processing_status="ready", workspace_id=workspace_id,
    )

    async with await _client() as client:
        response = await client.post(
            "/api/v1/diff",
            json={
                "base": {"resume_id": base["resume_id"]},
                "head": {"resume_id": head["resume_id"]},
                "mode": "tex",
            },
        )

    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    changed = [row for row in rows if row["status"] != "unchanged"]
    # Exactly the headline line moved, not the entire preamble.
    assert changed, "expected the headline change to show up"
    assert all("Distributed Systems Engineer" in (row["head_text"] or "")
               or "Engineer" in (row["base_text"] or "")
               for row in changed)
    assert len(changed) <= 4


async def test_tex_mode_compares_the_override_against_the_generated_source(
    isolated_db: Any,
) -> None:
    """The point of tex mode: see what hand-editing changed relative to what
    the document would have produced."""
    document = owner_document()
    resume = await isolated_db.create_resume(
        content="{}", content_type="document", processed_data=document,
        processing_status="ready",
        workspace_id=await isolated_db.default_workspace_id(),
    )
    resume_id = resume["resume_id"]
    mine = "\\documentclass{article}\n\\begin{document}\nhand written\n\\end{document}\n"

    async with await _client() as client:
        # A checkpoint whose source is still generated.
        assert (
            await client.patch(f"/api/v1/resumes/{resume_id}", json=document)
        ).status_code == 200
        clean = (
            await client.get(f"/api/v1/resumes/{resume_id}/versions")
        ).json()["versions"][0]["version_id"]

        await client.put(f"/api/v1/resumes/{resume_id}/tex", json={"source": mine})

        response = await client.post(
            "/api/v1/diff",
            json={
                "base": {"version_id": clean},
                "head": {"resume_id": resume_id},
                "mode": "tex",
            },
        )

    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert any("hand written" in (row["head_text"] or "") for row in rows)
    # The generated preamble is on the base side, not silently ignored.
    assert any("documentclass" in (row["base_text"] or "") for row in rows)
