"""The PDF export carries the caller's tenant into the print route.

Chromium fetches the Next print page over loopback, bypassing the gateway, so
it presents no ``X-Apps-*`` of its own. If the renderer does not forward the
caller's identity, the print page's own API call comes back unscoped — a 404 in
header mode, or worse, another tenant's document. This failure only appears in
the deployed configuration and only on export, which is exactly why it needs a
test.

Both render paths are covered: the shared process-wide browser and the threaded
fallback used where the event loop cannot spawn subprocesses.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import app.pdf as pdf_module
from app.main import app

pytestmark = pytest.mark.integration

TENANT = "anon-aaaa000000000000"


class RecordingPage:
    """Page double that records the headers the renderer installs."""

    def __init__(self, recorder: dict[str, Any]) -> None:
        self.recorder = recorder

    async def set_extra_http_headers(self, headers: dict[str, str]) -> None:
        self.recorder["headers"] = dict(headers)

    async def goto(self, url: str, **kwargs: Any) -> None:
        del kwargs
        self.recorder["url"] = url

    async def wait_for_selector(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    async def wait_for_function(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    async def pdf(self, *args: Any, **kwargs: Any) -> bytes:
        del args, kwargs
        return b"%PDF-1.4 synthetic"

    async def close(self) -> None:
        return None


class RecordingBrowser:
    def __init__(self, recorder: dict[str, Any]) -> None:
        self.recorder = recorder

    def is_connected(self) -> bool:
        return True

    async def new_page(self) -> RecordingPage:
        return RecordingPage(self.recorder)

    async def close(self) -> None:
        return None


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Install a fake shared browser and capture what the renderer sends."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(pdf_module, "_browser", RecordingBrowser(captured))
    monkeypatch.setattr(pdf_module, "_subprocess_supported", True)
    return captured


def _client(tenant: str | None = None, role: str = "anon") -> AsyncClient:
    headers = {}
    if tenant is not None:
        headers = {"X-Apps-Tenant": tenant, "X-Apps-Role": role}
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    )


async def _ready_resume(db: Any, workspace_id: str) -> str:
    resume = await db.create_resume(
        content="{}",
        content_type="json",
        title="CV",
        processing_status="ready",
        processed_data={"schemaVersion": 2, "header": {}, "sections": []},
        cover_letter="Dear hiring manager",
        workspace_id=workspace_id,
    )
    return str(resume["resume_id"])


async def test_the_resume_export_forwards_the_callers_workspace(
    isolated_db: Any, recorder: dict[str, Any]
) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _ready_resume(isolated_db, workspace_id)

    async with _client() as client:
        response = await client.get(f"/api/v1/resumes/{resume_id}/pdf")

    assert response.status_code == 200
    assert recorder["headers"] == {"X-Workspace-Id": workspace_id}


async def test_the_cover_letter_export_forwards_it_too(
    isolated_db: Any, recorder: dict[str, Any]
) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _ready_resume(isolated_db, workspace_id)

    async with _client() as client:
        response = await client.get(f"/api/v1/resumes/{resume_id}/cover-letter/pdf")

    assert response.status_code == 200
    assert recorder["headers"] == {"X-Workspace-Id": workspace_id}


async def test_the_tenant_ref_travels_in_header_mode(
    isolated_db: Any, recorder: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """In single mode there is no tenant ref to send; in header mode there is.

    ``X-Workspace-Id`` alone selects the right *profile* but not the right
    tenant, so both have to travel.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "tenant_mode", "header")

    async with _client(TENANT) as client:
        workspaces = (await client.get("/api/v1/workspaces")).json()["workspaces"]
        workspace_id = workspaces[0]["workspace_id"]
        resume_id = await _ready_resume(isolated_db, workspace_id)
        response = await client.get(f"/api/v1/resumes/{resume_id}/pdf")

    assert response.status_code == 200
    assert recorder["headers"] == {
        "X-Workspace-Id": workspace_id,
        "X-Apps-Tenant": TENANT,
    }


async def test_another_tenant_cannot_export_the_resume(
    isolated_db: Any, recorder: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The export 404s before Chromium is ever asked to render."""
    from app.config import settings

    monkeypatch.setattr(settings, "tenant_mode", "header")

    async with _client(TENANT) as client:
        workspace_id = (await client.get("/api/v1/workspaces")).json()["workspaces"][0][
            "workspace_id"
        ]
        resume_id = await _ready_resume(isolated_db, workspace_id)

    async with _client("anon-bbbb000000000000") as client:
        response = await client.get(f"/api/v1/resumes/{resume_id}/pdf")

    assert response.status_code == 404
    assert "headers" not in recorder


async def test_the_threaded_fallback_forwards_the_headers_too(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The subprocess-less path is a separate call chain and drifts silently.

    It is reached where the running loop cannot spawn a subprocess, which is
    where a missing parameter would never be noticed until a user's export came
    back empty.
    """
    captured: dict[str, Any] = {}

    async def fake_in_thread(
        url: str,
        selector: str,
        pdf_format: str,
        pdf_margins: dict,
        total_deadline: float,
        headers: dict[str, str] | None = None,
    ) -> Any:
        import asyncio

        captured["headers"] = headers

        async def _result() -> bytes:
            return b"%PDF-1.4 synthetic"

        return asyncio.create_task(_result())

    monkeypatch.setattr(pdf_module, "_browser", None)
    monkeypatch.setattr(pdf_module, "_subprocess_supported", False)
    monkeypatch.setattr(pdf_module, "_render_resume_pdf_in_thread", fake_in_thread)

    workspace_id = await isolated_db.default_workspace_id()
    resume_id = await _ready_resume(isolated_db, workspace_id)

    async with _client() as client:
        response = await client.get(f"/api/v1/resumes/{resume_id}/pdf")

    assert response.status_code == 200
    assert captured["headers"] == {"X-Workspace-Id": workspace_id}


async def test_the_tenant_ref_stays_out_of_the_error_message(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A render failure must not echo the tenant ref: it is a cookie hash."""
    from app.config import settings

    monkeypatch.setattr(settings, "tenant_mode", "header")

    async def failing_render(*args: Any, **kwargs: Any) -> bytes:
        del args, kwargs
        raise pdf_module.PDFRenderError("PDF rendering failed. Please try again.")

    monkeypatch.setattr(pdf_module, "render_resume_pdf", failing_render)
    import app.routers.resumes as resumes_module

    monkeypatch.setattr(resumes_module, "render_resume_pdf", failing_render)

    async with _client(TENANT) as client:
        workspace_id = (await client.get("/api/v1/workspaces")).json()["workspaces"][0][
            "workspace_id"
        ]
        resume_id = await _ready_resume(isolated_db, workspace_id)
        response = await client.get(f"/api/v1/resumes/{resume_id}/pdf")

    assert response.status_code == 503
    assert TENANT not in response.text
    assert workspace_id not in response.text
