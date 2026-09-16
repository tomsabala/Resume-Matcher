"""The dashboard reads recent AI failures from here.

Without this endpoint a truncated or rejected model answer left only a server
log line, and the UI could say nothing more useful than "please try again".
"""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai_events import (
    MAX_TRACKED_AI_FAILURES,
    clear_ai_failures,
    record_ai_failure,
)
from app.main import app

pytestmark = pytest.mark.integration


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _clean_tail() -> Any:
    clear_ai_failures()
    yield
    clear_ai_failures()


async def test_recorded_failures_are_served_newest_first() -> None:
    record_ai_failure(
        operation="resume",
        kind="truncated",
        detail="JSON response truncated: 1 unclosed object(s) after 5671 characters",
        model="anthropic/claude-opus-5",
        provider="anthropic",
        attempts=3,
        max_tokens=32768,
    )
    record_ai_failure(
        operation="diff", kind="invalid", detail="Validator rejected the answer"
    )

    async with _client() as client:
        response = await client.get("/api/v1/diagnostics/ai-failures")

    assert response.status_code == 200, response.text
    failures = response.json()["failures"]
    assert [f["operation"] for f in failures] == ["diff", "resume"]
    truncated = failures[1]
    assert truncated["kind"] == "truncated"
    assert truncated["max_tokens"] == 32768
    assert truncated["attempts"] == 3
    assert truncated["model"] == "anthropic/claude-opus-5"
    assert "5671 characters" in truncated["detail"]


async def test_no_failures_is_an_empty_list_not_an_error() -> None:
    async with _client() as client:
        response = await client.get("/api/v1/diagnostics/ai-failures")

    assert response.status_code == 200
    assert response.json()["failures"] == []


async def test_dismissing_clears_the_tail_and_reports_the_count() -> None:
    for index in range(3):
        record_ai_failure(operation=f"op-{index}", kind="provider", detail="boom")

    async with _client() as client:
        dismissed = await client.delete("/api/v1/diagnostics/ai-failures")
        after = await client.get("/api/v1/diagnostics/ai-failures")

    assert dismissed.json()["dismissed"] == 3
    assert after.json()["failures"] == []


async def test_the_tail_is_bounded_so_a_failing_provider_cannot_grow_it() -> None:
    for index in range(MAX_TRACKED_AI_FAILURES + 5):
        record_ai_failure(operation="resume", kind="provider", detail=f"failure {index}")

    async with _client() as client:
        failures = (await _client_get(client))["failures"]

    assert len(failures) == MAX_TRACKED_AI_FAILURES
    # The newest survive; the oldest five were dropped.
    assert "failure 24" in failures[0]["detail"]


async def _client_get(client: AsyncClient) -> dict[str, Any]:
    response = await client.get("/api/v1/diagnostics/ai-failures")
    assert response.status_code == 200, response.text
    return response.json()
