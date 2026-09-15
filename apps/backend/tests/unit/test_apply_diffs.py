"""Unit tests for apply_diffs() — path resolution, verification gates, and actions."""

import copy
from typing import Any

import pytest

from app.schemas.document import migrate_document
from app.schemas.models import ResumeChange
from app.services.improver import apply_diffs

# Paths used throughout, derived from the v2 `sample_resume` fixture.
SUMMARY = "sections.summary.text"
EXP_BULLETS = "sections.experience.entries[0].bullets"
SKILLS = "sections.skills.groups[0].values"
LANGUAGES = "sections.skills.groups[1].values"
CERTIFICATIONS = "sections.skills.groups[2].values"
AWARDS = "sections.skills.groups[3].values"


def _section(document: dict[str, Any], key: str) -> dict[str, Any]:
    return next(section for section in document["sections"] if section["key"] == key)


def _values(document: dict[str, Any], group_index: int) -> list[str]:
    return _section(document, "skills")["groups"][group_index]["values"]


def _bullet_texts(document: dict[str, Any], key: str, entry: int) -> list[str]:
    return [
        bullet["text"] for bullet in _section(document, key)["entries"][entry]["bullets"]
    ]


def _with_military_service(sample_resume: dict[str, Any]) -> dict[str, Any]:
    """A document with a user-created section — no code knows this key exists."""
    document = copy.deepcopy(sample_resume)
    document["sections"].append(
        {
            "id": "s-military",
            "key": "military_service",
            "heading": "Military Service",
            "headingI18nKey": None,
            "kind": "entries",
            "visible": True,
            "column": "main",
            "text": "",
            "entries": [
                {
                    "id": "e-signals",
                    "title": "Signals Officer",
                    "subtitle": "Corps of Engineers",
                    "meta": "Fort Ord, CA",
                    "period": "2012 - 2014",
                    "links": [],
                    "summary": "Led a signals platoon.",
                    "bullets": [
                        {"text": "Maintained field radio networks", "style": "bullet"},
                        {"text": "Trained 12 operators", "style": "bullet"},
                    ],
                }
            ],
            "tags": [],
            "groups": [],
        }
    )
    return document


def _with_spoken_languages(sample_resume: dict[str, Any]) -> dict[str, Any]:
    """A document with a user-created TAGS section (a flat list of values)."""
    document = copy.deepcopy(sample_resume)
    document["sections"].append(
        {
            "id": "s-languages",
            "key": "spoken_languages",
            "heading": "Spoken Languages",
            "headingI18nKey": None,
            "kind": "tags",
            "visible": True,
            "column": "side",
            "text": "",
            "entries": [],
            "tags": ["English", "Spanish"],
            "groups": [],
        }
    )
    return document


class TestApplyDiffsReplace:
    """Tests for the 'replace' action."""

    def test_replace_text_section(self, sample_resume):
        original_text = _section(sample_resume, "summary")["text"]
        changes = [
            ResumeChange(
                path=SUMMARY,
                action="replace",
                original=original_text,
                value="Updated summary text.",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert len(rejected) == 0
        assert _section(result, "summary")["text"] == "Updated summary text."

    def test_replace_bullet_text(self, sample_resume):
        original_bullet = _bullet_texts(sample_resume, "experience", 0)[1]
        changes = [
            ResumeChange(
                path=f"{EXP_BULLETS}[1].text",
                action="replace",
                original=original_bullet,
                value="Architected microservices migration serving 100K users",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert _bullet_texts(result, "experience", 0)[1] == changes[0].value

    def test_replace_project_bullet_text(self, sample_resume):
        original_bullet = _bullet_texts(sample_resume, "projects", 0)[0]
        changes = [
            ResumeChange(
                path="sections.projects.entries[0].bullets[0].text",
                action="replace",
                original=original_bullet,
                value="Python CLI tool generating API clients from OpenAPI specs",
                reason="Added Python keyword",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert _bullet_texts(result, "projects", 0)[0] == changes[0].value

    def test_replace_entry_summary(self, sample_resume):
        """An entry's narrative paragraph (education's prose) is editable."""
        original_summary = _section(sample_resume, "education")["entries"][0]["summary"]
        changes = [
            ResumeChange(
                path="sections.education.entries[0].summary",
                action="replace",
                original=original_summary,
                value="Graduated with honors; focus on distributed systems and APIs",
                reason="surface relevant coursework",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert len(rejected) == 0
        assert _section(result, "education")["entries"][0]["summary"] == changes[0].value

    def test_replace_case_insensitive_original_match(self, sample_resume):
        original_bullet = _bullet_texts(sample_resume, "experience", 0)[0]
        changes = [
            ResumeChange(
                path=f"{EXP_BULLETS}[0].text",
                action="replace",
                original=original_bullet.upper(),  # Case difference
                value="New text",
                reason="test",
            )
        ]
        _result, applied, _rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1

    def test_reject_bullet_list_replace_with_string(self, sample_resume):
        """`...bullets` is a list of objects; a string replace there is malformed."""
        changes = [
            ResumeChange(
                path=EXP_BULLETS,
                action="replace",
                original=None,
                value="One flattened bullet",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        assert _bullet_texts(result, "experience", 0) == _bullet_texts(
            sample_resume, "experience", 0
        )

    def test_reject_tag_list_replace_with_string(self, sample_resume):
        """`...tags` holds short values; a string replace there is malformed."""
        document = _with_spoken_languages(sample_resume)
        changes = [
            ResumeChange(
                path="sections.spoken_languages.tags",
                action="replace",
                original=None,
                value="English, Spanish, French",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(document, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        assert _section(result, "spoken_languages")["tags"] == ["English", "Spanish"]

    @pytest.mark.parametrize(
        "path",
        [
            EXP_BULLETS,
            "sections.spoken_languages.tags",
            SKILLS,
        ],
    )
    def test_list_replace_leaves_a_document_that_still_validates(
        self, sample_resume, path
    ):
        """The consequence of the guard: a replace aimed at a list must never
        swap that list for a bare string, because every downstream reader
        re-validates the document and a str-for-list would raise."""
        document = _with_spoken_languages(sample_resume)
        changes = [
            ResumeChange(
                path=path,
                action="replace",
                original=None,
                value="one flattened string",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(document, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        # Raises ValidationError if the list was flattened into a string.
        assert migrate_document(result).model_dump(mode="json") == migrate_document(
            document
        ).model_dump(mode="json")


class TestApplyDiffsAppend:
    """Tests for the 'append' action — bullet lists only."""

    def test_append_bullet_to_experience(self, sample_resume):
        original_count = len(_bullet_texts(sample_resume, "experience", 0))
        changes = [
            ResumeChange(
                path=EXP_BULLETS,
                action="append",
                original=None,
                value="Implemented CI/CD pipelines with GitHub Actions",
                reason="Added CI/CD keyword",
            )
        ]
        result, applied, _rejected = apply_diffs(sample_resume, changes)
        bullets = _section(result, "experience")["entries"][0]["bullets"]
        assert len(applied) == 1
        assert len(bullets) == original_count + 1
        # Appended as a Bullet object, not a bare string.
        assert bullets[-1] == {
            "text": "Implemented CI/CD pipelines with GitHub Actions",
            "style": "bullet",
        }

    def test_append_bullet_to_project(self, sample_resume):
        original_count = len(_bullet_texts(sample_resume, "projects", 0))
        changes = [
            ResumeChange(
                path="sections.projects.entries[0].bullets",
                action="append",
                original=None,
                value="Published to PyPI with 10K+ monthly downloads",
                reason="test",
            )
        ]
        result, applied, _rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert len(_bullet_texts(result, "projects", 0)) == original_count + 1

    def test_reject_append_to_group_values(self, sample_resume):
        """A short value must go through the verified `add_skill`; `append` would
        otherwise be an unverified back door into the same list."""
        changes = [
            ResumeChange(
                path=SKILLS,
                action="append",
                original=None,
                value="Kubernetes",
                reason="unverified skill smuggled in as an append",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Kubernetes"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert "Kubernetes" not in _values(result, 0)

    def test_reject_append_to_tags_section(self, sample_resume):
        """Same rule for a TAGS section's flat list of short values."""
        document = _with_spoken_languages(sample_resume)
        changes = [
            ResumeChange(
                path="sections.spoken_languages.tags",
                action="append",
                original=None,
                value="French",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(document, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        assert _section(result, "spoken_languages")["tags"] == ["English", "Spanish"]

    def test_append_empty_bullet_rejected(self, sample_resume):
        changes = [
            ResumeChange(
                path=EXP_BULLETS,
                action="append",
                original=None,
                value="   ",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        assert len(_bullet_texts(result, "experience", 0)) == len(
            _bullet_texts(sample_resume, "experience", 0)
        )


class TestApplyDiffsAddSkill:
    """Tests for adding verified skills to a short-value list."""

    def test_add_skill_to_group_values(self, sample_resume):
        changes = [
            ResumeChange(
                path=SKILLS,
                action="add_skill",
                original=None,
                value="Kubernetes",
                reason="JD-required skill approved by verifier",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Kubernetes"}],
        )
        assert len(applied) == 1
        assert len(rejected) == 0
        assert "Kubernetes" in _values(result, 0)

    def test_add_skill_rejects_unverified_skill(self, sample_resume):
        changes = [
            ResumeChange(
                path=SKILLS,
                action="add_skill",
                original=None,
                value="BananaDB",
                reason="Unsupported skill should not be appended",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Kubernetes"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert "BananaDB" not in _values(result, 0)

    def test_add_skill_rejects_duplicate_case_insensitive(self, sample_resume):
        changes = [
            ResumeChange(
                path=SKILLS,
                action="add_skill",
                original=None,
                value="python",
                reason="Duplicate skill should not be appended",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Python"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert _values(result, 0).count("Python") == 1

    def test_add_skill_rejects_non_skill_path(self, sample_resume):
        changes = [
            ResumeChange(
                path=SUMMARY,
                action="add_skill",
                original=None,
                value="Kubernetes",
                reason="Skill additions are only allowed in short-value lists",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Kubernetes"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert _section(result, "summary")["text"] == _section(sample_resume, "summary")["text"]

    def test_add_skill_rejects_bullet_list_path(self, sample_resume):
        changes = [
            ResumeChange(
                path=EXP_BULLETS,
                action="add_skill",
                original=None,
                value="Kubernetes",
                reason="bullets are not a skill list",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Kubernetes"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert "Kubernetes" not in " ".join(_bullet_texts(result, "experience", 0))


class TestApplyDiffsReorder:
    """Tests for the 'reorder' action."""

    def test_reorder_group_values(self, sample_resume):
        original_skills = _values(sample_resume, 0)
        reordered = list(reversed(original_skills))
        changes = [
            ResumeChange(
                path=SKILLS,
                action="reorder",
                original=None,
                value=reordered,
                reason="Prioritized relevant skills",
            )
        ]
        result, applied, _rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert _values(result, 0) == reordered

    def test_reorder_with_unverified_items_drops_them_keeps_originals(self, sample_resume):
        """Issue #736: a reorder mixing in new items is salvaged, not dropped —
        new items without a verified target are removed, originals preserved."""
        original = _values(sample_resume, 0)
        changes = [
            ResumeChange(
                path=SKILLS,
                action="reorder",
                original=None,
                value=["Python", "Kubernetes", "Go"],  # Kubernetes/Go new, no verified targets
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        skills = _values(result, 0)
        assert len(applied) == 1 and len(rejected) == 0
        assert "Kubernetes" not in skills and "Go" not in skills
        assert set(skills) == set(original)
        assert skills[0] == "Python"

    def test_reorder_case_insensitive_matching(self, sample_resume):
        original_skills = _values(sample_resume, 0)
        reordered = [s.lower() for s in reversed(original_skills)]
        changes = [
            ResumeChange(
                path=SKILLS,
                action="reorder",
                original=None,
                value=reordered,
                reason="test",
            )
        ]
        result, applied, _rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        # Original casing is restored, not the model's lowercase echo.
        assert _values(result, 0) == list(reversed(original_skills))

    def test_reorder_accepts_list_original_and_applies(self, sample_resume):
        # The live LLM ignores the prompt's `original: null` for reorder and sends
        # the current skills LIST as `original`. The schema must accept that — a
        # `str | None`-only `original` dropped the whole change at parse time with a
        # `string_type` error ("Skipping malformed change") — and a pure reorder
        # (same items, new order) must still apply.
        original_skills = _values(sample_resume, 0)
        reordered = list(reversed(original_skills))
        change = ResumeChange(
            path=SKILLS,
            action="reorder",
            original=original_skills,  # a LIST, exactly as the LLM sends it
            value=reordered,
            reason="prioritize JD-relevant skills",
        )
        assert change.original == original_skills
        result, applied, _rejected = apply_diffs(sample_resume, [change])
        assert len(applied) == 1
        assert _values(result, 0) == reordered

    def test_list_original_rejected_for_non_reorder_actions(self):
        # A list `original` is valid ONLY for reorder. For a text action like
        # replace it would bypass the original-match gate and crash the
        # invented-metrics check, so the schema rejects it at construction.
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ResumeChange(
                path=SUMMARY,
                action="replace",
                original=["a", "b"],  # list original on a text action — invalid
                value="new summary",
                reason="test",
            )


class TestApplyDiffsBlockedPaths:
    """Identity and structure are never editable, in any section."""

    @pytest.mark.parametrize(
        "path,original_val",
        [
            ("header.name", "Jane Doe"),
            ("header.headline", "Senior Backend Engineer"),
            ("header.contacts[0].value", "jane@example.com"),
        ],
    )
    def test_reject_header(self, sample_resume, path, original_val):
        changes = [
            ResumeChange(
                path=path, action="replace", original=original_val, value="X", reason="test"
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1
        assert len(applied) == 0
        assert result["header"] == sample_resume["header"]

    @pytest.mark.parametrize(
        "path,original_val",
        [
            ("sections.experience.entries[0].period", "Jan 2021 - Present"),
            ("sections.experience.entries[0].title", "Senior Backend Engineer"),
            ("sections.experience.entries[0].subtitle", "Acme Corp"),
            ("sections.experience.entries[0].meta", "San Francisco, CA"),
            ("sections.education.entries[0].title", "MIT"),
            ("sections.education.entries[0].subtitle", "B.S. Computer Science"),
            ("sections.projects.entries[0].subtitle", "Creator & Maintainer"),
        ],
    )
    def test_reject_entry_identity_fields(self, sample_resume, path, original_val):
        changes = [
            ResumeChange(
                path=path, action="replace", original=original_val, value="X", reason="test"
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result == sample_resume

    @pytest.mark.parametrize(
        "path",
        [
            "sections.summary.heading",
            "sections.summary.key",
            "sections.summary.kind",
            "sections.summary.visible",
            "sections.summary.column",
            "sections.experience.entries[0].id",
            "sections.experience.entries[0].bullets[0].style",
            "sections.skills.groups[0].label",
            "schemaVersion",
        ],
    )
    def test_reject_structural_fields(self, sample_resume, path):
        changes = [
            ResumeChange(path=path, action="replace", original=None, value="X", reason="test")
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result == sample_resume


class TestApplyDiffsUserCreatedSections:
    """A user-created section is a first-class AI edit target (the v1 allowlist
    blocked every custom section outright)."""

    def test_replace_bullet_in_user_section(self, sample_resume):
        document = _with_military_service(sample_resume)
        original_bullet = _bullet_texts(document, "military_service", 0)[0]
        changes = [
            ResumeChange(
                path="sections.military_service.entries[0].bullets[0].text",
                action="replace",
                original=original_bullet,
                value="Maintained field radio networks across three battalions",
                reason="surface the operations keyword from the JD",
            )
        ]
        result, applied, rejected = apply_diffs(document, changes)
        assert len(applied) == 1
        assert len(rejected) == 0
        assert _bullet_texts(result, "military_service", 0)[0] == changes[0].value

    def test_replace_summary_and_append_bullet_in_user_section(self, sample_resume):
        document = _with_military_service(sample_resume)
        entry = _section(document, "military_service")["entries"][0]
        changes = [
            ResumeChange(
                path="sections.military_service.entries[0].summary",
                action="replace",
                original=entry["summary"],
                value="Led a signals platoon of 12.",
                reason="test",
            ),
            ResumeChange(
                path="sections.military_service.entries[0].bullets",
                action="append",
                original=None,
                value="Ran comms for joint exercises",
                reason="test",
            ),
        ]
        result, applied, rejected = apply_diffs(document, changes)
        assert len(applied) == 2
        assert len(rejected) == 0
        merged = _section(result, "military_service")["entries"][0]
        assert merged["summary"] == "Led a signals platoon of 12."
        assert merged["bullets"][-1] == {
            "text": "Ran comms for joint exercises",
            "style": "bullet",
        }

    def test_user_section_entry_identity_still_blocked(self, sample_resume):
        document = _with_military_service(sample_resume)
        changes = [
            ResumeChange(
                path="sections.military_service.entries[0].subtitle",
                action="replace",
                original="Corps of Engineers",
                value="Special Forces",
                reason="identity is never editable, custom section or not",
            )
        ]
        result, applied, rejected = apply_diffs(document, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result == document

    def test_add_skill_to_user_created_group(self, sample_resume):
        """A user-created GROUPS section is a valid verified-skill target."""
        document = copy.deepcopy(sample_resume)
        document["sections"].append(
            {
                "id": "s-tooling",
                "key": "tooling",
                "heading": "Tooling",
                "headingI18nKey": None,
                "kind": "groups",
                "visible": True,
                "column": "side",
                "text": "",
                "entries": [],
                "tags": [],
                "groups": [{"label": "Platforms", "values": ["Linux"]}],
            }
        )
        changes = [
            ResumeChange(
                path="sections.tooling.groups[0].values",
                action="add_skill",
                original=None,
                value="Kubernetes",
                reason="JD-required, verified",
            )
        ]
        result, applied, rejected = apply_diffs(
            document, changes, allowed_skill_targets=[{"skill": "Kubernetes"}]
        )
        assert len(applied) == 1
        assert len(rejected) == 0
        assert _section(result, "tooling")["groups"][0]["values"] == [
            "Linux",
            "Kubernetes",
        ]


class TestApplyDiffsVerificationGates:
    """Tests for path resolution and original text verification."""

    def test_reject_out_of_bounds_index(self, sample_resume):
        changes = [
            ResumeChange(
                path="sections.experience.entries[99].bullets[0].text",
                action="replace",
                original="Nonexistent",
                value="New",
                reason="test",
            )
        ]
        _result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_reject_original_text_mismatch(self, sample_resume):
        changes = [
            ResumeChange(
                path=f"{EXP_BULLETS}[0].text",
                action="replace",
                original="This text does not exist anywhere in the resume",
                value="New text",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result == sample_resume

    def test_reject_unknown_action_at_schema_level(self, sample_resume):
        """Pydantic Literal type prevents invalid actions before apply_diffs sees them."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ResumeChange(
                path=SUMMARY,
                action="delete",  # type: ignore[arg-type]
                original=_section(sample_resume, "summary")["text"],
                value="",
                reason="test",
            )

    def test_reject_nonexistent_path(self, sample_resume):
        changes = [
            ResumeChange(
                path="nonexistent.field",
                action="replace",
                original="x",
                value="y",
                reason="test",
            )
        ]
        _result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_reject_unknown_section_key(self, sample_resume):
        """The allowlist is built from THIS document's sections, so a well-formed
        path naming a section the user does not have must be rejected."""
        changes = [
            ResumeChange(
                path="sections.military_service.entries[0].bullets[0].text",
                action="replace",
                original="Maintained field radio networks",
                value="Commanded a battalion",
                reason="section does not exist in this document",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result == sample_resume

    def test_reject_wrong_kind_for_section(self, sample_resume):
        """`experience` is an ENTRIES section, so its TEXT path is not editable."""
        changes = [
            ResumeChange(
                path="sections.experience.text",
                action="replace",
                original="",
                value="Prose smuggled into an entries section",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result == sample_resume


class TestApplyDiffsIntegrity:
    """Tests for data integrity and multi-change scenarios."""

    def test_does_not_mutate_original(self, sample_resume):
        original_copy = copy.deepcopy(sample_resume)
        changes = [
            ResumeChange(
                path=SUMMARY,
                action="replace",
                original=_section(sample_resume, "summary")["text"],
                value="Changed",
                reason="test",
            )
        ]
        result, _, _ = apply_diffs(sample_resume, changes)
        assert sample_resume == original_copy
        assert _section(result, "summary")["text"] == "Changed"

    def test_multiple_changes_partial_rejection(self, sample_resume):
        changes = [
            ResumeChange(
                path=SUMMARY,
                action="replace",
                original=_section(sample_resume, "summary")["text"],
                value="New summary",
                reason="good",
            ),
            ResumeChange(
                path="header.name",
                action="replace",
                original="Jane Doe",
                value="Bad",
                reason="blocked",
            ),
            ResumeChange(
                path=f"{EXP_BULLETS}[0].text",
                action="replace",
                original=_bullet_texts(sample_resume, "experience", 0)[0],
                value="Updated bullet",
                reason="good",
            ),
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 2
        assert len(rejected) == 1
        assert _section(result, "summary")["text"] == "New summary"
        assert result["header"]["name"] == "Jane Doe"  # Unchanged

    def test_empty_changes_list(self, sample_resume):
        result, applied, rejected = apply_diffs(sample_resume, [])
        assert len(applied) == 0
        assert len(rejected) == 0
        assert result == sample_resume

    def test_all_changes_applied(self, sample_resume, sample_changes):
        _result, applied, rejected = apply_diffs(sample_resume, sample_changes)
        assert len(rejected) == 0
        assert len(applied) == len(sample_changes)


class TestApplyDiffsEdgeCases:
    """Edge cases: hostile inputs, malformed paths, boundary conditions."""

    def test_append_to_non_list_rejected(self, sample_resume):
        """Append to a TEXT section should be rejected."""
        changes = [
            ResumeChange(
                path=SUMMARY,
                action="append",
                original=None,
                value="Extra text",
                reason="test",
            )
        ]
        _result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1
        assert len(applied) == 0

    def test_reorder_non_list_rejected(self, sample_resume):
        """Reorder on a TEXT section should be rejected."""
        changes = [
            ResumeChange(
                path=SUMMARY,
                action="reorder",
                original=None,
                value=["a", "b"],
                reason="test",
            )
        ]
        _result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_reorder_with_non_list_value_rejected(self, sample_resume):
        """Reorder where value is a string instead of list should be rejected."""
        changes = [
            ResumeChange(
                path=SKILLS,
                action="reorder",
                original=None,
                value="Python, Docker",  # type: ignore[arg-type]
                reason="test",
            )
        ]
        _result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_reorder_with_duplicates_is_deduped_and_preserves_originals(self, sample_resume):
        """Issue #736: a reorder with a duplicate and missing items is salvaged —
        the duplicate is collapsed and every original is preserved (no loss)."""
        original = _values(sample_resume, 0)
        changes = [
            ResumeChange(
                path=SKILLS,
                action="reorder",
                original=None,
                # Python duplicated, Redis/FastAPI missing
                value=["Python", "Python", "Docker", "AWS", "PostgreSQL"],
                reason="test",
            )
        ]
        result, applied, _rejected = apply_diffs(sample_resume, changes)
        skills = _values(result, 0)
        assert len(applied) == 1
        assert skills.count("Python") == 1  # duplicate collapsed
        assert set(skills) == set(original)  # nothing lost

    def test_empty_path_rejected(self, sample_resume):
        """Empty path string should be rejected."""
        changes = [
            ResumeChange(
                path="",
                action="replace",
                original="x",
                value="y",
                reason="test",
            )
        ]
        _result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_deeply_nested_invalid_path_rejected(self, sample_resume):
        """Path with too many segments that don't resolve."""
        changes = [
            ResumeChange(
                path=f"{EXP_BULLETS}[0].text.nested.deep",
                action="replace",
                original="x",
                value="y",
                reason="test",
            )
        ]
        _result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_negative_index_rejected(self, sample_resume):
        """Negative array index should not resolve."""
        changes = [
            ResumeChange(
                path="sections.experience.entries[-1].bullets[0].text",
                action="replace",
                original="x",
                value="y",
                reason="test",
            )
        ]
        _result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_second_entry_of_a_section(self, sample_resume):
        """Changes to the second entry should work and leave the first alone."""
        original_bullet = _bullet_texts(sample_resume, "experience", 1)[0]
        changes = [
            ResumeChange(
                path="sections.experience.entries[1].bullets[0].text",
                action="replace",
                original=original_bullet,
                value="Updated payment system description",
                reason="test",
            )
        ]
        result, applied, _rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert (
            _bullet_texts(result, "experience", 1)[0]
            == "Updated payment system description"
        )
        assert _bullet_texts(result, "experience", 0) == _bullet_texts(
            sample_resume, "experience", 0
        )

    def test_section_paths_follow_the_key_not_the_position(self, sample_resume):
        """Section order is user-editable, so a path must resolve by key."""
        document = copy.deepcopy(sample_resume)
        document["sections"].reverse()
        original_text = _section(document, "summary")["text"]
        changes = [
            ResumeChange(
                path=SUMMARY,
                action="replace",
                original=original_text,
                value="Reordered but still addressable.",
                reason="test",
            )
        ]
        result, applied, _rejected = apply_diffs(document, changes)
        assert len(applied) == 1
        assert _section(result, "summary")["text"] == "Reordered but still addressable."


class TestApplyDiffsOtherGroups:
    """Every group of short values is reorderable, not just the first."""

    @pytest.mark.parametrize(
        "path,group_index",
        [(LANGUAGES, 1), (CERTIFICATIONS, 2), (AWARDS, 3)],
    )
    def test_reorder_other_groups(self, sample_resume, path, group_index):
        original = _values(sample_resume, group_index)
        changes = [
            ResumeChange(
                path=path,
                action="reorder",
                original=None,
                value=list(reversed(original)),
                reason="prioritize for this role",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert len(rejected) == 0
        assert _values(result, group_index) == list(reversed(original))

    def test_reject_out_of_range_group_index(self, sample_resume):
        changes = [
            ResumeChange(
                path="sections.skills.groups[9].values",
                action="reorder",
                original=None,
                value=["Anything"],
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result == sample_resume


class TestReorderSalvage:
    """Issue #736: a reorder whose items don't exactly match the original must be
    SALVAGED, not dropped wholesale — reorder existing items, never lose an
    original, and add new items only when they pass the verified gate."""

    def test_reorder_with_verified_new_skill_is_salvaged(self, sample_resume):
        original = _values(sample_resume, 0)  # 6 items
        changes = [
            ResumeChange(
                path=SKILLS,
                action="reorder",
                original=None,
                value=[
                    "FastAPI",
                    "Python",
                    "Docker",
                    "AWS",
                    "PostgreSQL",
                    "Redis",
                    "Kubernetes",
                ],
                reason="surface JD skills; Kubernetes is JD-required",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume, changes, allowed_skill_targets=[{"skill": "Kubernetes"}]
        )
        skills = _values(result, 0)
        assert len(applied) == 1 and len(rejected) == 0
        assert "Kubernetes" in skills  # verified new skill added
        assert set(original).issubset(set(skills))  # no original lost
        assert skills[0] == "FastAPI"  # LLM order honored

    def test_reorder_with_unverified_new_skill_drops_only_that_skill(self, sample_resume):
        original = _values(sample_resume, 0)
        changes = [
            ResumeChange(
                path=SKILLS,
                action="reorder",
                original=None,
                value=["Redis", "Python", "FastAPI", "Docker", "AWS", "PostgreSQL", "Rust"],
                reason="Rust is not in the verified targets",
            )
        ]
        result, applied, _rejected = apply_diffs(
            sample_resume, changes, allowed_skill_targets=[{"skill": "Kubernetes"}]
        )
        skills = _values(result, 0)
        assert len(applied) == 1  # salvaged, not rejected
        assert "Rust" not in skills  # unverified addition dropped
        assert set(original).issubset(set(skills))  # originals preserved
        assert skills[0] == "Redis"

    def test_reorder_omitting_original_skill_preserves_it(self, sample_resume):
        original = _values(sample_resume, 0)
        changes = [
            ResumeChange(
                path=SKILLS,
                action="reorder",
                original=None,
                value=["Redis", "Python"],  # omits 4 originals
                reason="prioritize two skills",
            )
        ]
        result, applied, _rejected = apply_diffs(sample_resume, changes)
        skills = _values(result, 0)
        assert len(applied) == 1
        assert set(skills) == set(original)  # nothing lost
        assert skills[:2] == ["Redis", "Python"]  # requested order first

    def test_reorder_other_group_with_unverified_new_item_drops_it(self, sample_resume):
        original = _values(sample_resume, 1)  # Languages
        changes = [
            ResumeChange(
                path=LANGUAGES,
                action="reorder",
                original=None,
                value=[
                    "Spanish (Conversational)",
                    "English (Native)",
                    "French (Fluent)",
                ],
                reason="no verified target for French — must not fabricate",
            )
        ]
        result, applied, _rejected = apply_diffs(sample_resume, changes)
        langs = _values(result, 1)
        assert len(applied) == 1
        assert "French (Fluent)" not in langs  # no fabrication
        assert set(langs) == set(original)

    def test_pure_permutation_still_applies(self, sample_resume):
        """Regression: an exact permutation keeps working unchanged."""
        changes = [
            ResumeChange(
                path=SKILLS,
                action="reorder",
                original=None,
                value=["Redis", "PostgreSQL", "AWS", "Docker", "FastAPI", "Python"],
                reason="pure reorder",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1 and len(rejected) == 0
        assert _values(result, 0) == [
            "Redis",
            "PostgreSQL",
            "AWS",
            "Docker",
            "FastAPI",
            "Python",
        ]

    def test_salvage_places_verified_new_skill_in_requested_position(self, sample_resume):
        """PR #830 review (Copilot): a verified new skill the model puts near the
        top of the reorder must land there, not be appended last."""
        changes = [
            ResumeChange(
                path=SKILLS,
                action="reorder",
                original=None,
                value=[
                    "Kubernetes",
                    "Python",
                    "FastAPI",
                    "Docker",
                    "AWS",
                    "PostgreSQL",
                    "Redis",
                ],
                reason="prioritize Kubernetes (JD-required, verified)",
            )
        ]
        result, _applied, _rejected = apply_diffs(
            sample_resume, changes, allowed_skill_targets=[{"skill": "Kubernetes"}]
        )
        skills = _values(result, 0)
        assert skills[0] == "Kubernetes"  # requested position honored, not appended last
        assert set(_values(sample_resume, 0)).issubset(set(skills))

    def test_salvage_preserves_case_duplicate_originals(self, sample_resume):
        """PR #830 review (kilo): case-duplicate originals must not be lost."""
        document = copy.deepcopy(sample_resume)
        _section(document, "skills")["groups"][0]["values"] = [
            "python",
            "Python",
            "Docker",
        ]
        changes = [
            ResumeChange(
                path=SKILLS,
                action="reorder",
                original=None,
                # Go new+unverified, both pythons are originals
                value=["Docker", "python", "Go"],
                reason="test dup handling",
            )
        ]
        result, applied, _rejected = apply_diffs(document, changes)
        skills = _values(result, 0)
        assert len(applied) == 1
        # Both case-variants of the original survive; the unverified new item is dropped.
        assert sorted(skills) == sorted(["python", "Python", "Docker"])
        assert "Go" not in skills
