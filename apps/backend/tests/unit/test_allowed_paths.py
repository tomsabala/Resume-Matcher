"""The AI edit allowlist is generated from the document, not hardcoded.

This is what makes a user-created section AI-editable: v1 blocked every
``customSections`` path outright, so a "Military Service" section could never
be tailored.
"""

from typing import Any

import pytest

from app.schemas.document import ResumeDocument
from app.services.improver import _is_path_allowed, _is_path_blocked, build_allowed_paths

pytestmark = pytest.mark.unit


def _section(key: str, kind: str, **content: Any) -> dict[str, Any]:
    return {
        "id": f"s-{key}",
        "key": key,
        "heading": key.replace("_", " ").title(),
        "kind": kind,
        "visible": True,
        "column": "main",
        "text": "",
        "entries": [],
        "tags": [],
        "groups": [],
        **content,
    }


@pytest.fixture
def document() -> ResumeDocument:
    return ResumeDocument.model_validate(
        {
            "schemaVersion": 2,
            "header": {"name": "Tom", "headline": "", "contacts": []},
            "sections": [
                _section("summary", "text", text="hi"),
                _section(
                    "military_service",
                    "entries",
                    entries=[
                        {
                            "id": "e1",
                            "title": "Officer",
                            "subtitle": "Unit 8200",
                            "meta": "",
                            "period": "2010",
                            "links": [],
                            "summary": "led a team",
                            "bullets": [{"text": "did a thing", "style": "bullet"}],
                        }
                    ],
                ),
                _section("spoken", "tags", tags=["Hebrew"]),
                _section(
                    "skills",
                    "groups",
                    groups=[{"label": "Systems", "values": ["Linux"]}],
                ),
            ],
        }
    )


def _allowed(document: ResumeDocument, path: str) -> bool:
    return _is_path_allowed(path, build_allowed_paths(document)) and not _is_path_blocked(
        path
    )


@pytest.mark.parametrize(
    "path",
    [
        "sections.summary.text",
        "sections.military_service.entries[0].summary",
        "sections.military_service.entries[0].bullets",
        "sections.military_service.entries[0].bullets[0].text",
        "sections.spoken.tags",
        "sections.skills.groups[0].values",
    ],
)
def test_content_paths_are_editable(document: ResumeDocument, path: str) -> None:
    assert _allowed(document, path) is True


@pytest.mark.parametrize(
    "path",
    [
        # Identity: who the user is, and who/where/when each entry describes.
        "header",
        "header.name",
        "header.contacts[0].value",
        "sections.military_service.entries[0].title",
        "sections.military_service.entries[0].subtitle",
        "sections.military_service.entries[0].period",
        "sections.military_service.entries[0].meta",
        "sections.military_service.entries[0].links",
        # Structure: the AI edits content, it does not author the document.
        "sections.summary.heading",
        "sections.summary.key",
        "sections.summary.visible",
        "sections.military_service.entries[0].id",
        "sections.skills.groups[0].label",
        "sections.military_service.entries[0].bullets[0].style",
        # A section this document does not have.
        "sections.publications.text",
        # Right section, wrong shape for its kind.
        "sections.summary.entries[0].bullets[0].text",
        "sections.spoken.groups[0].values",
    ],
)
def test_identity_structure_and_unknown_paths_are_refused(
    document: ResumeDocument, path: str
) -> None:
    assert _allowed(document, path) is False


def test_allowlist_follows_the_document_not_a_fixed_section_list() -> None:
    """Rename the section and the old path stops being editable."""
    document = ResumeDocument.model_validate(
        {
            "schemaVersion": 2,
            "header": {"name": "", "headline": "", "contacts": []},
            "sections": [_section("about_me", "text", text="hi")],
        }
    )

    assert _allowed(document, "sections.about_me.text") is True
    assert _allowed(document, "sections.summary.text") is False
