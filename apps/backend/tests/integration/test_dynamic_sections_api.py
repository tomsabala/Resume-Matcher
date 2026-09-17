"""End-to-end proof that resume sections are data, not code.

The v1 model declared six sections and Pydantic's default ``extra='ignore'``,
so any section the code did not know about was silently discarded on every
write. These tests pin the opposite behaviour.
"""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.document import migrate_document
from app.services.improver import _is_path_allowed, build_allowed_paths

pytestmark = pytest.mark.integration


def _entry(entry_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": entry_id,
        "title": "",
        "subtitle": "",
        "meta": "",
        "period": "",
        "links": [],
        "summary": "",
        "bullets": [],
        **fields,
    }


def _section(key: str, heading: str, kind: str, **content: Any) -> dict[str, Any]:
    return {
        "id": f"s-{key}",
        "key": key,
        "heading": heading,
        "headingI18nKey": None,
        "kind": kind,
        "visible": True,
        "column": "main",
        "text": "",
        "entries": [],
        "tags": [],
        "groups": [],
        **content,
    }


def owner_document() -> dict[str, Any]:
    """The owner's real resume shape — unrepresentable under the v1 schema.

    It has a top-level Military Service section, an entry carrying *both* a
    paragraph and bullets, and arbitrary skill-group labels.
    """
    return {
        "schemaVersion": 2,
        "header": {
            "name": "Tom",
            "headline": "Systems & AI Engineer",
            "contacts": [
                {
                    "id": "c1",
                    "kind": "github",
                    "label": "",
                    "value": "github.com/tom",
                    "url": "",
                }
            ],
        },
        "sections": [
            _section("about_me", "About Me", "text", text="Engineer."),
            _section(
                "experience",
                "Work Experience",
                "entries",
                entries=[
                    _entry(
                        "e-work",
                        title="Engineer",
                        subtitle="Acme",
                        period="2023 -- May 2026",
                        summary="Owned the platform end to end.",
                        bullets=[
                            {"text": "Shipped the thing", "style": "bullet"},
                            {"text": "A plain note", "style": "plain"},
                        ],
                    )
                ],
            ),
            _section(
                "military_service",
                "Military Service",
                "entries",
                entries=[
                    _entry(
                        "e-mil",
                        title="Team Lead",
                        subtitle="Unit 8200",
                        period="2016 -- 2019",
                        bullets=[{"text": "Led a signals team", "style": "bullet"}],
                    )
                ],
            ),
            _section(
                "skills",
                "Skills",
                "groups",
                groups=[
                    {"label": "Languages", "values": ["Python", "Rust"]},
                    {"label": "Backend & Systems", "values": ["Linux", "gRPC"]},
                    {"label": "AI", "values": ["PyTorch"]},
                    {"label": "Cloud & Infrastructure", "values": ["AWS"]},
                ],
            ),
        ],
    }


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_a_document_with_user_sections_round_trips_unchanged(
    isolated_db: Any,
) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    resume = await isolated_db.create_resume(
        content="{}", content_type="json", workspace_id=workspace_id
    )
    document = owner_document()

    async with await _client() as client:
        written = await client.patch(
            f"/api/v1/resumes/{resume['resume_id']}", json=document
        )
        assert written.status_code == 200, written.text
        read = await client.get(
            "/api/v1/resumes", params={"resume_id": resume["resume_id"]}
        )

    stored = read.json()["data"]["processed_resume"]
    assert stored["sections"] == document["sections"]
    assert stored["header"] == document["header"]


async def test_unknown_top_level_keys_are_rejected_not_silently_dropped(
    isolated_db: Any,
) -> None:
    """The v1 model ignored extras, so a whole section could vanish on save."""
    workspace_id = await isolated_db.default_workspace_id()
    resume = await isolated_db.create_resume(
        content="{}", content_type="json", workspace_id=workspace_id
    )
    payload = owner_document() | {"customSections": {"Ghost": {"sectionType": "text"}}}

    async with await _client() as client:
        response = await client.patch(
            f"/api/v1/resumes/{resume['resume_id']}", json=payload
        )

    assert response.status_code == 422


async def test_user_created_sections_are_ai_editable(isolated_db: Any) -> None:
    """``customSections`` was in the v1 blocked-prefix set; nothing in it could
    ever be tailored."""
    document = migrate_document(owner_document())
    allowed = build_allowed_paths(document)

    assert _is_path_allowed(
        "sections.military_service.entries[0].bullets[0].text", allowed
    )
    assert _is_path_allowed("sections.skills.groups[2].values", allowed)


async def test_a_legacy_row_is_projected_on_read(isolated_db: Any) -> None:
    legacy = {
        "personalInfo": {"name": "Old", "title": "Dev", "email": "old@example.com"},
        "summary": "legacy summary",
        "workExperience": [
            {
                "title": "Dev",
                "company": "Legacy Inc",
                "years": "2015 - 2018",
                "description": ["a", "b"],
                "descriptionStyles": ["plain"],
            }
        ],
    }
    resume = await isolated_db.create_resume(
        content="{}",
        content_type="json",
        processed_data=legacy,
        workspace_id=await isolated_db.default_workspace_id(),
    )

    async with await _client() as client:
        read = await client.get(
            "/api/v1/resumes", params={"resume_id": resume["resume_id"]}
        )

    stored = read.json()["data"]["processed_resume"]
    assert stored["schemaVersion"] == 2
    assert stored["header"]["name"] == "Old"
    assert [section["key"] for section in stored["sections"]] == [
        "summary",
        "experience",
    ]
    bullets = stored["sections"][1]["entries"][0]["bullets"]
    assert [(b["text"], b["style"]) for b in bullets] == [("a", "plain"), ("b", "bullet")]
