"""Resume version history: dedup, coalescing, lineage and atomicity."""

import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from sqlalchemy import select

from app import database
from app.config import settings
from app.main import app
from app.models import Resume, ResumeVersion

from tests.integration.test_dynamic_sections_api import owner_document

pytestmark = pytest.mark.integration


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _with_summary(text: str) -> dict[str, Any]:
    document = owner_document()
    document["sections"][0]["text"] = text
    return document


async def _seeded_resume(db: Any, workspace_id: str) -> str:
    resume = await db.create_resume(
        content="{}",
        content_type="json",
        processed_data=owner_document(),
        workspace_id=workspace_id,
    )
    await db.seed_resume_version(
        resume["resume_id"], workspace_id=workspace_id, origin="import"
    )
    return str(resume["resume_id"])


async def test_identical_content_does_not_create_a_version(isolated_db: Any) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)
    first = await isolated_db.commit_resume_version(
        resume_id, _with_summary("one"), workspace_id=workspace_id, origin="ai_tailor"
    )
    again = await isolated_db.commit_resume_version(
        resume_id, _with_summary("one"), workspace_id=workspace_id, origin="ai_tailor"
    )

    assert again["version_id"] == first["version_id"]
    assert (
        len(
            await isolated_db.list_resume_versions(
                resume_id, workspace_id=workspace_id
            )
        )
        == 2
    )


async def test_consecutive_manual_saves_coalesce_into_one_version(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Builder autosave fires on every pause; the history must not grow by one
    row per keystroke pause."""
    monkeypatch.setattr(settings, "resume_version_coalesce_seconds", 300)
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)

    first = await isolated_db.commit_resume_version(
        resume_id,
        _with_summary("draft one"),
        workspace_id=workspace_id,
        origin="manual",
    )
    second = await isolated_db.commit_resume_version(
        resume_id,
        _with_summary("draft two"),
        workspace_id=workspace_id,
        origin="manual",
    )

    assert second["version_id"] == first["version_id"]
    versions = await isolated_db.list_resume_versions(
        resume_id, workspace_id=workspace_id
    )
    assert [v["origin"] for v in versions] == ["manual", "import"]
    head = await isolated_db.get_resume_version(
        second["version_id"], workspace_id=workspace_id
    )
    assert head["document"]["sections"][0]["text"] == "draft two"


async def test_a_save_after_the_window_starts_a_new_version(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "resume_version_coalesce_seconds", 0)
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)

    first = await isolated_db.commit_resume_version(
        resume_id,
        _with_summary("draft one"),
        workspace_id=workspace_id,
        origin="manual",
    )
    second = await isolated_db.commit_resume_version(
        resume_id,
        _with_summary("draft two"),
        workspace_id=workspace_id,
        origin="manual",
    )

    assert second["version_id"] != first["version_id"]
    assert second["parent_version_id"] == first["version_id"]


@pytest.mark.parametrize("origin", ["ai_tailor", "ai_enrich", "wizard", "restore"])
async def test_non_manual_origins_never_coalesce(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    """Every AI or import checkpoint must stay individually restorable."""
    monkeypatch.setattr(settings, "resume_version_coalesce_seconds", 3600)
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)

    first = await isolated_db.commit_resume_version(
        resume_id, _with_summary("one"), workspace_id=workspace_id, origin=origin
    )
    second = await isolated_db.commit_resume_version(
        resume_id, _with_summary("two"), workspace_id=workspace_id, origin=origin
    )

    assert second["version_id"] != first["version_id"]


async def test_labelled_or_pinned_head_is_never_overwritten(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "resume_version_coalesce_seconds", 3600)
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)
    first = await isolated_db.commit_resume_version(
        resume_id, _with_summary("one"), workspace_id=workspace_id, origin="manual"
    )
    await isolated_db.update_resume_version(
        first["version_id"], {"is_pinned": True}, workspace_id=workspace_id
    )

    second = await isolated_db.commit_resume_version(
        resume_id, _with_summary("two"), workspace_id=workspace_id, origin="manual"
    )

    assert second["version_id"] != first["version_id"]
    kept = await isolated_db.get_resume_version(
        first["version_id"], workspace_id=workspace_id
    )
    assert kept["document"]["sections"][0]["text"] == "one"


async def test_restore_appends_rather_than_rewinding(isolated_db: Any) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)
    original = (
        await isolated_db.list_resume_versions(resume_id, workspace_id=workspace_id)
    )[0]
    await isolated_db.commit_resume_version(
        resume_id,
        _with_summary("rewritten by ai"),
        workspace_id=workspace_id,
        origin="ai_tailor",
    )

    async with await _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/restore",
            json={"version_id": original["version_id"]},
        )
    assert response.status_code == 200, response.text
    restored = response.json()

    assert restored["origin"] == "restore"
    assert restored["origin_ref"] == original["version_id"]
    versions = await isolated_db.list_resume_versions(
        resume_id, workspace_id=workspace_id
    )
    assert [v["origin"] for v in versions] == ["restore", "ai_tailor", "import"]
    assert restored["parent_version_id"] == versions[1]["version_id"]

    head = await isolated_db.get_resume_version(
        restored["version_id"], workspace_id=workspace_id
    )
    source = await isolated_db.get_resume_version(
        original["version_id"], workspace_id=workspace_id
    )
    assert head["document"] == source["document"]
    resume = await isolated_db.get_resume(resume_id, workspace_id=workspace_id)
    assert resume["processed_data"] == source["document"]


async def test_the_version_row_and_head_pointer_commit_together(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure *after* the version row is staged must leave nothing behind.

    The row and the resume's head pointer move in one transaction, so a crash
    between them can never produce a version no resume points at.
    """
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)
    before = await isolated_db.list_resume_versions(
        resume_id, workspace_id=workspace_id
    )

    real_deepcopy = database.copy.deepcopy
    calls = {"count": 0}

    def failing_deepcopy(value: Any) -> Any:
        # Call 1 stores the document on the staged version row; call 2 writes
        # it back onto the resume. Failing the second lands us mid-commit.
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("synthetic failure after the version row is staged")
        return real_deepcopy(value)

    monkeypatch.setattr(database.copy, "deepcopy", failing_deepcopy)
    with pytest.raises(RuntimeError):
        await isolated_db.commit_resume_version(
            resume_id,
            _with_summary("never lands"),
            workspace_id=workspace_id,
            origin="ai_tailor",
        )
    monkeypatch.undo()
    assert calls["count"] == 2

    after = await isolated_db.list_resume_versions(
        resume_id, workspace_id=workspace_id
    )
    assert [v["version_id"] for v in after] == [v["version_id"] for v in before]

    async with isolated_db._session() as session:
        rows = (await session.execute(select(ResumeVersion))).scalars().all()
        resume = await session.get(Resume, resume_id)
    assert {row.version_id for row in rows} == {resume.head_version_id}


async def test_history_is_listed_newest_first_without_documents(
    isolated_db: Any,
) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)
    await isolated_db.commit_resume_version(
        resume_id,
        _with_summary("second"),
        workspace_id=workspace_id,
        origin="ai_tailor",
    )

    async with await _client() as client:
        response = await client.get(f"/api/v1/resumes/{resume_id}/versions")

    body = response.json()
    assert [v["origin"] for v in body["versions"]] == ["ai_tailor", "import"]
    assert body["versions"][0]["is_head"] is True
    assert "document" not in body["versions"][0]


async def test_head_and_pinned_versions_refuse_deletion(isolated_db: Any) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)
    first = (
        await isolated_db.list_resume_versions(resume_id, workspace_id=workspace_id)
    )[0]
    second = await isolated_db.commit_resume_version(
        resume_id,
        _with_summary("second"),
        workspace_id=workspace_id,
        origin="ai_tailor",
    )

    async with await _client() as client:
        head = await client.delete(f"/api/v1/versions/{second['version_id']}")
        assert head.status_code == 409

        await client.patch(
            f"/api/v1/versions/{first['version_id']}", json={"is_pinned": True}
        )
        pinned = await client.delete(f"/api/v1/versions/{first['version_id']}")
        assert pinned.status_code == 409

        await client.patch(
            f"/api/v1/versions/{first['version_id']}", json={"is_pinned": False}
        )
        removed = await client.delete(f"/api/v1/versions/{first['version_id']}")
        assert removed.status_code == 200

    assert (
        await isolated_db.get_resume_version(
            first["version_id"], workspace_id=workspace_id
        )
        is None
    )


async def test_deleting_a_version_reparents_its_children(isolated_db: Any) -> None:
    """Lineage must stay walkable; a child must never point at a missing id."""
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)
    first = (
        await isolated_db.list_resume_versions(resume_id, workspace_id=workspace_id)
    )[0]
    middle = await isolated_db.commit_resume_version(
        resume_id,
        _with_summary("middle"),
        workspace_id=workspace_id,
        origin="ai_tailor",
    )
    last = await isolated_db.commit_resume_version(
        resume_id, _with_summary("last"), workspace_id=workspace_id, origin="ai_tailor"
    )
    assert last["parent_version_id"] == middle["version_id"]

    await isolated_db.delete_resume_version(
        middle["version_id"], workspace_id=workspace_id
    )

    reparented = await isolated_db.get_resume_version(
        last["version_id"], workspace_id=workspace_id
    )
    assert reparented["parent_version_id"] == first["version_id"]


async def test_a_builder_save_is_recorded_as_a_version(isolated_db: Any) -> None:
    """The acceptance path: editing in the builder produces history."""
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)

    async with await _client() as client:
        response = await client.patch(
            f"/api/v1/resumes/{resume_id}", json=_with_summary("edited in the builder")
        )
    assert response.status_code == 200, response.text

    versions = await isolated_db.list_resume_versions(
        resume_id, workspace_id=workspace_id
    )
    assert [v["origin"] for v in versions] == ["manual", "import"]
    head = await isolated_db.get_resume_version(
        versions[0]["version_id"], workspace_id=workspace_id
    )
    assert head["document"]["sections"][0]["text"] == "edited in the builder"


async def test_concurrent_saves_serialize_into_a_consistent_head(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "resume_version_coalesce_seconds", 0)
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _seeded_resume(isolated_db, workspace_id)

    await asyncio.gather(
        *(
            isolated_db.commit_resume_version(
                resume_id,
                _with_summary(f"save {index}"),
                workspace_id=workspace_id,
                origin="ai_tailor",
            )
            for index in range(5)
        )
    )

    resume = await isolated_db.get_resume(resume_id, workspace_id=workspace_id)
    head = await isolated_db.get_resume_version(
        resume["head_version_id"], workspace_id=workspace_id
    )
    assert head is not None
    assert resume["processed_data"] == head["document"]
