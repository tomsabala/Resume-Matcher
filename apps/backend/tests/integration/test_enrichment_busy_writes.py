"""Enrichment writes retain retryable storage outcomes at the HTTP boundary."""

import copy
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import Database
from app.main import app
from app.routers import enrichment
from tests.integration.test_storage_busy_writes import fast_busy_database  # noqa: F401


def _section(document: dict[str, Any], key: str) -> dict[str, Any]:
    return next(s for s in document["sections"] if s["key"] == key)


def _apply_request(
    resume_id: str,
    source: dict[str, Any],
    operation: str,
) -> tuple[str, dict[str, Any] | list[dict[str, Any]]]:
    """Build a valid public request that changes one existing experience."""
    entry = _section(source, "experience")["entries"][0]
    bullets = [bullet["text"] for bullet in entry["bullets"]]
    if operation == "apply":
        payload: dict[str, Any] | list[dict[str, Any]] = {
            "enhancements": [{
                "item_id": f"experience:{entry['id']}",
                "item_type": "entry",
                "section_heading": "Experience",
                "title": entry["title"],
                "subtitle": entry["subtitle"],
                "original_description": bullets,
                "enhanced_description": ["Built a reliable service"],
            }],
        }
    else:
        payload = [{
            "item_id": f"experience:{entry['id']}",
            "item_type": "entry",
            "title": entry["title"],
            "subtitle": entry["subtitle"],
            "original_content": bullets,
            "new_content": ["Built a reliable service"],
            "diff_summary": "Synthetic regeneration",
        }]
    return f"/api/v1/enrichment/{operation}/{resume_id}", payload


@pytest.mark.parametrize("operation", ["apply", "apply-regenerated"])
async def test_enrichment_write_contention_returns_503_and_retry_commits(
    fast_busy_database: Database,
    sample_resume: dict[str, Any],
    operation: str,
) -> None:
    database = fast_busy_database
    workspace_id = await database.default_workspace_id()
    source = await database.create_resume(
        content="Synthetic original",
        processed_data=sample_resume,
        processing_status="ready",
        workspace_id=workspace_id,
    )
    url, payload = _apply_request(source["resume_id"], sample_resume, operation)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        async with database._session() as writer:
            await writer.execute(text("BEGIN IMMEDIATE"))
            response = await client.post(url, json=payload)
            unchanged = await database.get_resume(
                source["resume_id"], workspace_id=workspace_id
            )
            assert unchanged is not None
            assert unchanged["content"] == "Synthetic original"
            assert unchanged["processed_data"] == sample_resume

        assert response.status_code == 503, response.text
        assert response.headers["retry-after"] == "1"
        assert response.json() == {"detail": "Database is busy. Please retry shortly."}
        retried = await client.post(url, json=payload)
        assert retried.status_code == 200, retried.text
        assert retried.json()["updated_items"] == 1

    expected = copy.deepcopy(sample_resume)
    added = {"text": "Built a reliable service", "style": "bullet"}
    entry = _section(expected, "experience")["entries"][0]
    entry["bullets"] = (
        entry["bullets"] + [added] if operation == "apply" else [added]
    )
    stored = await database.get_resume(source["resume_id"], workspace_id=workspace_id)
    assert stored is not None and stored["processed_data"] == expected


@pytest.mark.parametrize("operation", ["apply", "apply-regenerated"])
async def test_other_enrichment_write_failure_remains_generic_500(
    isolated_db: Database,
    sample_resume: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    source = await isolated_db.create_resume(
        content="Synthetic original",
        processed_data=sample_resume,
        processing_status="ready",
        workspace_id=workspace_id,
    )
    monkeypatch.setattr(
        isolated_db,
        "commit_resume_version",
        AsyncMock(side_effect=RuntimeError("synthetic private persistence detail")),
    )
    url, payload = _apply_request(source["resume_id"], sample_resume, operation)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(url, json=payload)
    assert response.status_code == 500
    assert "retry-after" not in response.headers
    assert response.json() == {"detail": (
        "Failed to save enhancements. Please try again."
        if operation == "apply" else "Failed to save changes. Please try again."
    )}
    stored = await isolated_db.get_resume(source["resume_id"], workspace_id=workspace_id)
    assert stored is not None and stored["processed_data"] == sample_resume


async def test_enhance_preview_does_not_write_under_sqlite_contention(
    fast_busy_database: Database,
    sample_resume: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = fast_busy_database
    workspace_id = await database.default_workspace_id()
    source = await database.create_resume(
        content="Synthetic original",
        processed_data=sample_resume,
        processing_status="ready",
        workspace_id=workspace_id,
    )
    monkeypatch.setattr(
        enrichment,
        "complete_json",
        AsyncMock(return_value={"additional_bullets": ["Built a reliable service"]}),
    )
    item_id = f"experience:{_section(sample_resume, 'experience')['entries'][0]['id']}"
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        async with database._session() as writer:
            await writer.execute(text("BEGIN IMMEDIATE"))
            response = await client.post("/api/v1/enrichment/enhance", json={
                "resume_id": source["resume_id"],
                "answers": [{
                    "item_id": item_id,
                    "question_id": "q-exp",
                    "answer": "Built a reliable service",
                }],
            })
    assert response.status_code == 200, response.text
    assert response.json()["enhancements"][0]["enhanced_description"] == [
        "Built a reliable service",
    ]
    stored = await database.get_resume(source["resume_id"], workspace_id=workspace_id)
    assert stored is not None and stored["processed_data"] == sample_resume
