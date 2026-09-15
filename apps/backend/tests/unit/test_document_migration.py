"""v1 → v2 document projection.

The projection is the only place the old six-section schema still exists. Every
case here is a shape the v1 model either mangled or could not represent at all.
"""

from typing import Any

import pytest

from app.schemas.document import SectionKind, migrate_document

pytestmark = pytest.mark.unit


def _v1(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "personalInfo": {
            "name": "Tom",
            "title": "Engineer",
            "email": "tom@example.com",
            "phone": "+972-000",
            "location": "Tel Aviv",
            "website": "https://tom.dev",
            "linkedin": "linkedin.com/in/tom",
            "github": "github.com/tom",
        },
        "summary": "A summary",
        "workExperience": [
            {
                "title": "SWE",
                "company": "Acme",
                "location": "TLV",
                "years": "2020 - 2024",
                "description": ["first", "second", "third"],
                "descriptionStyles": ["plain"],
            }
        ],
        "education": [
            {
                "institution": "Uni",
                "degree": "BSc",
                "years": "2016 - 2020",
                "description": "Graduated with honours",
            }
        ],
        "personalProjects": [
            {
                "name": "Tool",
                "role": "Author",
                "years": "2023",
                "github": "github.com/tom/tool",
                "description": ["did a thing"],
            }
        ],
        "additional": {
            "technicalSkills": ["Python"],
            "languages": ["Hebrew"],
            "certificationsTraining": [],
            "awards": [],
        },
    }
    base.update(overrides)
    return base


def test_projects_the_six_builtins_with_translation_keys() -> None:
    document = migrate_document(_v1())

    assert [(s.key, s.kind) for s in document.sections] == [
        ("summary", SectionKind.TEXT),
        ("experience", SectionKind.ENTRIES),
        ("education", SectionKind.ENTRIES),
        ("projects", SectionKind.ENTRIES),
        ("skills", SectionKind.GROUPS),
    ]
    assert [s.headingI18nKey for s in document.sections] == [
        "resume.sections.summary",
        "resume.sections.experience",
        "resume.sections.education",
        "resume.sections.projects",
        "resume.sections.skills",
    ]


def test_short_description_styles_array_pads_with_bullet() -> None:
    """The v1 arrays were index-aligned by hand and routinely ran short."""
    document = migrate_document(_v1())

    bullets = document.section("experience").entries[0].bullets
    assert [(b.text, b.style) for b in bullets] == [
        ("first", "plain"),
        ("second", "bullet"),
        ("third", "bullet"),
    ]


def test_education_scalar_description_becomes_a_summary_not_a_bullet() -> None:
    entry = migrate_document(_v1()).section("education").entries[0]

    assert entry.summary == "Graduated with honours"
    assert entry.bullets == []


def test_project_urls_become_links() -> None:
    entry = migrate_document(_v1()).section("projects").entries[0]

    assert [(link.kind, link.url) for link in entry.links] == [
        ("github", "github.com/tom/tool")
    ]


def test_social_contacts_are_icon_only() -> None:
    contacts = {c.kind: c for c in migrate_document(_v1()).header.contacts}

    assert contacts["email"].label == "tom@example.com"
    assert contacts["github"].label == ""
    assert contacts["github"].value == "github.com/tom"
    assert contacts["linkedin"].label == ""


def test_additional_buckets_become_labelled_groups_and_empties_are_dropped() -> None:
    groups = migrate_document(_v1()).section("skills").groups

    assert [(g.label, g.values) for g in groups] == [
        ("Technical Skills", ["Python"]),
        ("Languages", ["Hebrew"]),
    ]


def test_custom_sections_become_first_class_sections() -> None:
    document = migrate_document(
        _v1(
            customSections={
                "Military Service": {
                    "sectionType": "itemList",
                    "items": [
                        {
                            "title": "Officer",
                            "subtitle": "Unit 8200",
                            "years": "2010 - 2013",
                            "description": ["led a team"],
                        }
                    ],
                }
            }
        )
    )

    section = document.section("military_service")
    assert section is not None
    assert section.kind is SectionKind.ENTRIES
    assert section.heading == "Military Service"
    assert section.headingI18nKey is None
    assert section.entries[0].subtitle == "Unit 8200"


def test_section_meta_supplies_heading_visibility_and_order() -> None:
    document = migrate_document(
        _v1(
            sectionMeta=[
                {"id": "workExperience", "order": 0},
                {"id": "summary", "displayName": "About Me", "order": 1},
                {"id": "education", "order": 2, "isVisible": False},
            ]
        )
    )

    assert [s.key for s in document.sections][:3] == [
        "experience",
        "summary",
        "education",
    ]
    assert document.section("summary").heading == "About Me"
    assert document.section("education").visible is False
    # Unlisted sections keep their data rather than disappearing.
    assert document.section("projects") is not None


def test_section_meta_referencing_absent_data_is_dropped() -> None:
    """v1 injected DEFAULT_SECTION_META independently of the data, so a meta
    row for an empty section was routine; materialising it would print a bare
    heading on the user's PDF."""
    document = migrate_document(
        {
            "summary": "only this",
            "sectionMeta": [
                {"id": "summary", "order": 0},
                {"id": "workExperience", "displayName": "Experience", "order": 1},
            ],
        }
    )

    assert [s.key for s in document.sections] == ["summary"]


def test_v2_payloads_pass_through_unchanged() -> None:
    document = migrate_document(_v1())
    round_tripped = migrate_document(document.model_dump(mode="json"))

    assert round_tripped.model_dump(mode="json") == document.model_dump(mode="json")


def test_garbage_input_yields_an_empty_document_rather_than_raising() -> None:
    """This runs on every read path; a corrupt row must not 500 the request."""
    assert migrate_document(None).sections == []
    assert migrate_document("not a resume").sections == []
    assert migrate_document({"schemaVersion": 1, "nonsense": True}).sections == []
