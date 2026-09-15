"""Final AI-output preservation and grounding policy controls."""

import copy
from typing import Any
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import pytest

from app.schemas.document import ResumeDocument
from app.services.parser import restore_dates_from_markdown
from app.services.refiner import refine_resume
from app.services.resume_preservation import (
    GROUNDING_REVIEW_CODE,
    finalize_ai_resume,
    grounding_review_warnings,
    validate_confirmed_resume,
)
from app.schemas.refinement import RefinementConfig
from app.routers import resumes


# --- document helpers ------------------------------------------------------


def _canonical(document: dict[str, Any]) -> dict[str, Any]:
    """Schema round-trip, so a fixture compares equal to a finalizer result."""
    return ResumeDocument.model_validate(document).model_dump(mode="json")


def _entry(
    entry_id: str,
    title: str,
    subtitle: str,
    period: str,
    bullets: list[tuple[str, str]] | None = None,
    summary: str = "",
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "title": title,
        "subtitle": subtitle,
        "period": period,
        "summary": summary,
        "bullets": [{"text": text, "style": style} for text, style in (bullets or [])],
    }


def _source_document() -> dict[str, Any]:
    """A source resume with a plain bullet, a duplicate-prone identity, a
    narrative-only education entry and a user-created section."""
    return _canonical(
        {
            "schemaVersion": 2,
            "header": {
                "name": "Ada Lovelace",
                "contacts": [
                    {
                        "id": "c-email",
                        "kind": "email",
                        "label": "ada@example.com",
                        "value": "ada@example.com",
                    }
                ],
            },
            "sections": [
                {
                    "id": "s-summary",
                    "key": "summary",
                    "heading": "Summary",
                    "kind": "text",
                    "text": "Backend engineer building Python services.",
                },
                {
                    "id": "s-experience",
                    "key": "experience",
                    "heading": "Experience",
                    "kind": "entries",
                    "entries": [
                        _entry(
                            "e-alpha",
                            "Engineer",
                            "Alpha",
                            "Jan 2020 - Mar 2021",
                            [
                                ("Built Python APIs", "plain"),
                                ("Documented releases", "bullet"),
                            ],
                        ),
                        _entry(
                            "e-beta",
                            "Lead",
                            "Beta",
                            "Apr 2020 - Dec 2021",
                            [("Led service migrations", "bullet")],
                        ),
                    ],
                },
                {
                    "id": "s-education",
                    "key": "education",
                    "heading": "Education",
                    "kind": "entries",
                    "entries": [
                        _entry(
                            "e-university",
                            "Example University",
                            "BSc",
                            "2016 - 2020",
                            summary="Computer science",
                        )
                    ],
                },
                {
                    "id": "s-projects",
                    "key": "projects",
                    "heading": "Projects",
                    "kind": "entries",
                    "entries": [
                        _entry(
                            "e-parser",
                            "Parser",
                            "Maintainer",
                            "May 2021 - Present",
                            [("Parsed documents", "plain")],
                        )
                    ],
                },
                {
                    "id": "s-skills",
                    "key": "skills",
                    "heading": "Skills",
                    "kind": "groups",
                    "groups": [
                        {"label": "Technical Skills", "values": ["Python"]},
                        {"label": "Languages", "values": ["English"]},
                        {"label": "Certifications & Training", "values": []},
                        {"label": "Awards", "values": []},
                    ],
                },
                {
                    "id": "s-talks",
                    "key": "talks",
                    "heading": "Talks",
                    "kind": "entries",
                    "entries": [
                        _entry(
                            "e-talk",
                            "Reliable systems",
                            "PyCon",
                            "Jun 2023",
                            [("Presented testing methods", "plain")],
                        )
                    ],
                },
            ],
        }
    )


def _section(document: dict[str, Any], key: str) -> dict[str, Any]:
    return next(section for section in document["sections"] if section["key"] == key)


def _entries(document: dict[str, Any], key: str = "experience") -> list[dict[str, Any]]:
    return _section(document, key)["entries"]


def _bullets(
    document: dict[str, Any], key: str = "experience", entry: int = 0
) -> list[dict[str, Any]]:
    return _entries(document, key)[entry]["bullets"]


def _texts(
    document: dict[str, Any], key: str = "experience", entry: int = 0
) -> list[str]:
    return [bullet["text"] for bullet in _bullets(document, key, entry)]


def _styles(
    document: dict[str, Any], key: str = "experience", entry: int = 0
) -> list[str]:
    return [bullet["style"] for bullet in _bullets(document, key, entry)]


def _set_texts(
    document: dict[str, Any],
    texts: list[str],
    key: str = "experience",
    entry: int = 0,
) -> None:
    """Rewrite an entry's bullet texts the way a model does: default styles."""
    _entries(document, key)[entry]["bullets"] = [
        {"text": text, "style": "bullet"} for text in texts
    ]


def _values(document: dict[str, Any], label: str = "Technical Skills") -> list[str]:
    groups = _section(document, "skills")["groups"]
    return next(group for group in groups if group["label"] == label)["values"]


def _set_values(
    document: dict[str, Any], values: list[str], label: str = "Technical Skills"
) -> None:
    groups = _section(document, "skills")["groups"]
    next(group for group in groups if group["label"] == label)["values"] = values


def _header_only(source: dict[str, Any], summary: str) -> dict[str, Any]:
    """What a lazy writer returns: the header plus one rewritten section."""
    return {
        "schemaVersion": 2,
        "header": copy.deepcopy(source["header"]),
        "sections": [
            {
                "id": "s-summary",
                "key": "summary",
                "heading": "Summary",
                "kind": "text",
                "text": summary,
            }
        ],
    }


POPULATED_KEYS = ("experience", "education", "projects", "skills", "talks")


def test_final_writer_cannot_erase_populated_source_sections() -> None:
    source = _source_document()
    partial = _header_only(source, "Python backend engineer.")

    finalized = finalize_ai_resume(source, partial)

    assert _section(finalized, "summary")["text"] == "Python backend engineer."
    for key in POPULATED_KEYS:
        assert _section(finalized, key) == _section(source, key)


def test_final_writer_drops_a_section_the_ai_invented() -> None:
    """Tailoring edits content; the source document owns the structure."""
    source = _source_document()
    candidate = copy.deepcopy(source)
    candidate["sections"].append(
        {
            "id": "s-invented",
            "key": "publications",
            "heading": "Publications",
            "kind": "entries",
            "entries": [_entry("e-x", "A paper", "Journal", "2023")],
        }
    )

    finalized = finalize_ai_resume(source, candidate)

    assert [section["key"] for section in finalized["sections"]] == [
        section["key"] for section in source["sections"]
    ]


def test_header_is_restored_wholesale() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    candidate["header"]["name"] = "Ada L."
    candidate["header"]["contacts"][0]["value"] = "ada@fake.example"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["header"] == source["header"]


def test_reordered_entries_keep_their_identity_dates_and_styles() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    candidate["sections"] = [
        section for section in candidate["sections"] if section["key"] != "experience"
    ]
    reordered = [
        copy.deepcopy(_entries(source)[1]),
        copy.deepcopy(_entries(source)[0]),
    ]
    experience = copy.deepcopy(_section(source, "experience"))
    experience["entries"] = reordered
    candidate["sections"].append(experience)
    for entry in reordered:
        entry["period"] = "2020 - 2021"
    reordered[0]["bullets"] = [
        {"text": "Led migrations of services", "style": "bullet"}
    ]
    reordered[1]["bullets"] = [
        {"text": "Built scalable Python APIs", "style": "bullet"},
        {"text": "Documented release processes", "style": "bullet"},
    ]

    finalized = finalize_ai_resume(source, candidate)

    # Candidate order is honoured; identity, dates and styles come from source.
    assert [entry["id"] for entry in _entries(finalized)] == ["e-beta", "e-alpha"]
    assert _entries(finalized)[0]["period"] == "Apr 2020 - Dec 2021"
    assert _styles(finalized, entry=0) == ["bullet"]
    assert _entries(finalized)[1]["period"] == "Jan 2020 - Mar 2021"
    assert _styles(finalized, entry=1) == ["plain", "bullet"]


def test_reordered_bullet_rows_remain_confirmable_with_bound_styles() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    _set_texts(candidate, ["Documented releases", "Built Python APIs"])

    finalized = finalize_ai_resume(source, candidate)

    # The plain row travels with its text, not with its position.
    assert _texts(finalized) == ["Documented releases", "Built Python APIs"]
    assert _styles(finalized) == ["bullet", "plain"]
    assert validate_confirmed_resume(source, finalized) == []


def test_plain_bullet_survives_an_ai_rewrite() -> None:
    """The user's unbulleted paragraph row is formatting, not content: a model
    that rewrites the text and returns the default style cannot flip it."""
    source = _source_document()
    candidate = copy.deepcopy(source)
    _set_texts(
        candidate, ["Built scalable Python APIs", "Documented release processes"]
    )

    finalized = finalize_ai_resume(source, candidate)

    assert _texts(finalized) == [
        "Built scalable Python APIs",
        "Documented release processes",
    ]
    assert _styles(finalized) == ["plain", "bullet"]


def test_missing_model_id_falls_back_to_entry_identity() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    candidate_entry = _entries(candidate)[0]
    candidate_entry["id"] = ""
    candidate_entry["period"] = "2020 - 2021"

    finalized = finalize_ai_resume(source, candidate)

    assert _entries(finalized)[0]["id"] == "e-alpha"
    assert _entries(finalized)[0]["period"] == "Jan 2020 - Mar 2021"


async def test_real_refiner_final_writer_restores_partial_sections() -> None:
    source = _source_document()
    master = copy.deepcopy(source)
    _values(master).append("Kubernetes")
    partial = _header_only(source, "Kubernetes backend engineer.")

    with patch(
        "app.services.refiner.complete_json",
        new_callable=AsyncMock,
        return_value=partial,
    ):
        result = await refine_resume(
            initial_tailored=source,
            master_resume=master,
            job_description="Backend role requiring Kubernetes",
            job_keywords={
                "required_skills": ["Kubernetes"],
                "preferred_skills": [],
                "keywords": [],
            },
            config=RefinementConfig(
                enable_keyword_injection=True,
                enable_ai_phrase_removal=False,
                enable_master_alignment_check=True,
            ),
        )

    assert _section(result.refined_data, "summary")["text"] == (
        "Kubernetes backend engineer."
    )
    for key in POPULATED_KEYS:
        assert _section(result.refined_data, key) == _section(source, key)


async def test_real_refiner_binds_styles_to_reordered_entry_identity() -> None:
    source = _source_document()
    master = copy.deepcopy(source)
    _values(master).append("Kubernetes")
    candidate = copy.deepcopy(source)
    _section(candidate, "summary")["text"] = "Kubernetes backend engineer."
    _section(candidate, "experience")["entries"] = [
        copy.deepcopy(_entries(source)[1]),
        copy.deepcopy(_entries(source)[0]),
    ]
    _set_texts(candidate, ["Led migrations of services"], entry=0)
    _set_texts(
        candidate, ["Built scalable Python APIs", "Documented releases"], entry=1
    )

    with patch(
        "app.services.refiner.complete_json",
        new_callable=AsyncMock,
        return_value=candidate,
    ):
        result = await refine_resume(
            initial_tailored=source,
            master_resume=master,
            job_description="Backend role requiring Kubernetes",
            job_keywords={
                "required_skills": ["Kubernetes"],
                "preferred_skills": [],
                "keywords": [],
            },
            config=RefinementConfig(
                enable_keyword_injection=True,
                enable_ai_phrase_removal=False,
                enable_master_alignment_check=True,
            ),
        )

    assert [entry["id"] for entry in _entries(result.refined_data)] == [
        "e-beta",
        "e-alpha",
    ]
    assert _styles(result.refined_data, entry=0) == ["bullet"]
    assert _styles(result.refined_data, entry=1) == ["plain", "bullet"]


async def test_restored_unsafe_writer_attempt_is_not_counted_as_applied() -> None:
    source = _source_document()
    master = copy.deepcopy(source)
    _values(master).append("Kubernetes")
    partial = _header_only(source, _section(source, "summary")["text"])

    with patch(
        "app.services.refiner.complete_json",
        new_callable=AsyncMock,
        return_value=partial,
    ) as writer:
        result = await refine_resume(
            initial_tailored=source,
            master_resume=master,
            job_description="Backend role requiring Kubernetes",
            job_keywords={"required_skills": ["Kubernetes"]},
            config=RefinementConfig(
                enable_keyword_injection=True,
                enable_ai_phrase_removal=False,
                enable_master_alignment_check=False,
            ),
        )

    assert writer.await_count == 1
    assert result.passes_attempted == 1
    assert result.passes_completed == 0
    assert result.refined_data == source


def test_confirm_validation_allows_reorder_but_rejects_loss_and_identity_drift() -> (
    None
):
    source = _source_document()
    reordered = copy.deepcopy(source)
    _section(reordered, "experience")["entries"].reverse()
    assert validate_confirmed_resume(source, reordered) == []

    missing = copy.deepcopy(source)
    _section(missing, "experience")["entries"] = []
    assert "sections.experience.entries" in validate_confirmed_resume(source, missing)

    mutated = copy.deepcopy(source)
    _entries(mutated)[0]["subtitle"] = "Moon Base"
    assert "sections.experience.entries" in validate_confirmed_resume(source, mutated)

    drifted = copy.deepcopy(source)
    _entries(drifted)[0]["period"] = "2019 - 2021"
    assert "sections.experience.identity" in validate_confirmed_resume(source, drifted)

    dropped_section = copy.deepcopy(source)
    dropped_section["sections"] = [
        section for section in dropped_section["sections"] if section["key"] != "talks"
    ]
    assert "sections.talks" in validate_confirmed_resume(source, dropped_section)

    user_section_drift = copy.deepcopy(source)
    _entries(user_section_drift, "talks")[0]["period"] = "2024"
    assert "sections.talks.identity" in validate_confirmed_resume(
        source, user_section_drift
    )


def test_confirm_accepts_schema_defaults_absent_from_a_sparse_source() -> None:
    """A stored document may omit optional fields; the confirm payload is the
    schema-complete round-trip. That difference is not a violation."""
    sparse = {
        "schemaVersion": 2,
        "header": {"name": "Ada Lovelace"},
        "sections": [
            {
                "id": "s-experience",
                "key": "experience",
                "heading": "Experience",
                "kind": "entries",
                "entries": [
                    {
                        "id": "e-alpha",
                        "title": "Engineer",
                        "subtitle": "Alpha",
                        "period": "Jan 2020 - Mar 2021",
                        "bullets": [{"text": "Built Python APIs"}],
                    }
                ],
            }
        ],
    }

    assert validate_confirmed_resume(sparse, _canonical(sparse)) == []


def test_confirm_rejects_dropped_group_values_but_allows_verified_additions() -> None:
    """Short-value additions reach a candidate only through the verified
    ``add_skill`` gate, so they are accepted; a dropped value never is."""
    source = _source_document()

    added = copy.deepcopy(source)
    _values(added, "Languages").append("Spanish")
    assert validate_confirmed_resume(source, added) == []

    dropped = copy.deepcopy(source)
    _set_values(dropped, [], "Languages")
    assert "sections.skills.groups[1]" in validate_confirmed_resume(source, dropped)


def test_verified_jd_skill_addition_remains_while_original_lists_are_preserved() -> (
    None
):
    source = _source_document()
    candidate = copy.deepcopy(source)
    _set_values(candidate, ["Kubernetes"])

    finalized = finalize_ai_resume(source, candidate)

    assert _values(finalized) == ["Kubernetes", "Python"]
    assert validate_confirmed_resume(source, finalized) == []


def test_new_metrics_require_source_evidence_but_legitimate_rephrasing_remains() -> (
    None
):
    source = _source_document()
    candidate = copy.deepcopy(source)
    _set_texts(candidate, ["Built scalable Python APIs", "Managed 800 people"])

    finalized = finalize_ai_resume(source, candidate)

    assert _texts(finalized) == ["Built scalable Python APIs", "Documented releases"]


def test_equivalent_metric_notation_remains_editable() -> None:
    source = _source_document()
    _bullets(source)[0]["text"] = "Handled 50K requests with 40% fewer errors"
    candidate = copy.deepcopy(source)
    _bullets(candidate)[0]["text"] = (
        "Handled 50 thousand requests with 40 percent fewer errors"
    )

    finalized = finalize_ai_resume(source, candidate)

    assert _texts(finalized)[0] == (
        "Handled 50 thousand requests with 40 percent fewer errors"
    )


def test_metric_multiplicity_and_glued_units_are_grounded() -> None:
    source = _source_document()
    _bullets(source)[0]["text"] = "Reduced latency by 10%"
    candidate = copy.deepcopy(source)
    _bullets(candidate)[0]["text"] = (
        "Reduced 10% latency and added another 10% improvement"
    )
    _bullets(candidate)[1]["text"] = "Reduced latency by 5ms"

    finalized = finalize_ai_resume(source, candidate)

    assert _texts(finalized) == ["Reduced latency by 10%", "Documented releases"]


def test_versions_years_and_equivalent_scaled_counts_are_not_novel_metrics() -> None:
    source = _source_document()
    _bullets(source)[0]["text"] = "Served 1,000,000 users"
    candidate = copy.deepcopy(source)
    _bullets(candidate)[0]["text"] = "Served 1 million users with Python 3.9 in 2021"

    finalized = finalize_ai_resume(source, candidate)

    assert "1 million" in _texts(finalized)[0]


@pytest.mark.parametrize(
    ("source_row", "candidate_row"),
    [
        ("Migrated 150 servers", "Migrated 2000 servers"),
        ("Managed systems in 150 stores", "Managed systems in 2000 stores"),
    ],
    ids=["plain-count", "count-after-preposition"],
)
def test_count_in_year_range_is_not_mistaken_for_a_date(
    source_row: str,
    candidate_row: str,
) -> None:
    source = _source_document()
    _bullets(source)[0]["text"] = source_row
    candidate = copy.deepcopy(source)
    _bullets(candidate)[0]["text"] = candidate_row

    finalized = finalize_ai_resume(source, candidate)

    assert _texts(finalized)[0] == source_row


@pytest.mark.parametrize(
    ("source_row", "candidate_row"),
    [
        (
            "Reduced deployment time",
            "Reduced deployment time by automating release pipelines across EMEA",
        ),
        (
            "Built auth for five services and integrated SSO",
            "Built auth for services",
        ),
    ],
    ids=["unsupported-expansion", "unsupported-truncation"],
)
def test_subset_rewrite_is_restored_or_flagged_for_review(
    source_row: str,
    candidate_row: str,
) -> None:
    source = _source_document()
    _entries(source)[0]["bullets"] = [{"text": source_row, "style": "bullet"}]
    candidate = copy.deepcopy(source)
    _bullets(candidate)[0]["text"] = candidate_row

    strict = finalize_ai_resume(source, candidate, allow_review_claims=False)
    preview = finalize_ai_resume(source, candidate, allow_review_claims=True)

    assert _texts(strict) == [source_row]
    assert _texts(preview) == [candidate_row]
    assert grounding_review_warnings(source, preview) == [
        f"{GROUNDING_REVIEW_CODE}: Review "
        "sections.experience.entries[0].bullets[0] against the source resume."
    ]


def test_moderate_grounded_expansion_remains_editable_without_warning() -> None:
    source = _source_document()
    _entries(source)[0]["bullets"] = [{"text": "Built Python APIs", "style": "bullet"}]
    candidate = copy.deepcopy(source)
    _bullets(candidate)[0]["text"] = "Built scalable Python APIs"

    finalized = finalize_ai_resume(source, candidate, allow_review_claims=False)

    assert _texts(finalized) == ["Built scalable Python APIs"]
    assert grounding_review_warnings(source, finalized) == []


def test_restorable_reordered_metric_consumes_its_matched_source_row() -> None:
    source = _source_document()
    _set_texts(
        source,
        ["Led team of 5 engineers", "Built REST API", "Reduced costs by 10%"],
    )
    candidate = copy.deepcopy(source)
    _set_texts(
        candidate,
        ["Reduced costs by 15%", "Built REST API", "Led team of 5 engineers"],
    )

    finalized = finalize_ai_resume(source, candidate)

    assert _texts(finalized) == [
        "Reduced costs by 10%",
        "Built REST API",
        "Led team of 5 engineers",
    ]


def test_candidate_rows_are_normalized_before_the_confirmation_contract() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    _set_texts(candidate, ["Built Python APIs\nDeployed to AWS", "•"])

    finalized = finalize_ai_resume(source, candidate)
    round_tripped = _canonical(finalized)

    assert len(_bullets(round_tripped)) == 2
    assert validate_confirmed_resume(source, round_tripped) == []


def test_verified_append_can_survive_finalization() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    _bullets(candidate).append(
        {"text": "Documented release processes for Python APIs", "style": "bullet"}
    )

    finalized = finalize_ai_resume(source, candidate, allow_appended_rows=True)

    assert _texts(finalized)[-1] == "Documented release processes for Python APIs"


def test_appended_row_is_dropped_when_appends_are_not_allowed() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    _bullets(candidate).append(
        {"text": "Documented release processes for Python APIs", "style": "bullet"}
    )

    finalized = finalize_ai_resume(source, candidate)

    assert _texts(finalized) == _texts(source)


def test_ungrounded_preview_append_receives_review_warning() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    _bullets(candidate).append(
        {
            "text": "Spearheaded an industry consortium on resume parsing",
            "style": "bullet",
        }
    )

    finalized = finalize_ai_resume(source, candidate, allow_appended_rows=True)

    assert _texts(finalized)[-1] == (
        "Spearheaded an industry consortium on resume parsing"
    )
    assert grounding_review_warnings(source, finalized) == [
        f"{GROUNDING_REVIEW_CODE}: Review "
        "sections.experience.entries[0].bullets[2] against the source resume."
    ]


def test_direct_flow_drops_unreviewed_ungrounded_append() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    _bullets(candidate).append(
        {"text": "Commanded unrelated lunar expeditions", "style": "bullet"}
    )

    finalized = finalize_ai_resume(
        source,
        candidate,
        allow_review_claims=False,
        allow_appended_rows=True,
    )

    assert _texts(finalized) == _texts(source)


def test_entry_without_source_narrative_rejects_an_invented_one() -> None:
    source = _source_document()
    _entries(source, "education")[0]["summary"] = ""
    candidate = copy.deepcopy(source)
    _entries(candidate, "education")[0]["summary"] = "Invented honors"

    strict = finalize_ai_resume(source, candidate, allow_review_claims=False)

    assert _entries(strict, "education")[0]["summary"] == ""


def test_blank_entry_narrative_restores_source() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    _entries(candidate, "education")[0]["summary"] = " "

    finalized = finalize_ai_resume(source, candidate)

    assert _entries(finalized, "education")[0]["summary"] == "Computer science"


def test_duplicate_entry_identity_uses_bullets_to_keep_both_rewrites() -> None:
    source = _source_document()
    duplicate = copy.deepcopy(_entries(source)[0])
    duplicate["id"] = "e-alpha-2"
    duplicate["bullets"] = [{"text": "Maintained data pipelines", "style": "bullet"}]
    _entries(source).append(duplicate)
    candidate = copy.deepcopy(source)
    for entry in _entries(candidate):
        entry["id"] = ""
    _set_texts(candidate, ["Built reliable Python APIs"], entry=0)
    _set_texts(candidate, ["Maintained ETL pipelines"], entry=2)

    finalized = finalize_ai_resume(source, candidate)

    assert len(_entries(finalized)) == 3
    assert {entry["id"] for entry in _entries(finalized)} == {
        "e-alpha",
        "e-beta",
        "e-alpha-2",
    }


def test_confirm_accepts_reordered_entries_with_duplicate_field_identity() -> None:
    source = _source_document()
    first = _entries(source)[0]
    duplicate = copy.deepcopy(first)
    duplicate["id"] = "e-alpha-2"
    duplicate["period"] = "Apr 2021 - Dec 2023"
    duplicate["bullets"] = [{"text": "Maintained data pipelines", "style": "plain"}]
    _section(source, "experience")["entries"] = [first, duplicate]
    candidate = copy.deepcopy(source)
    _section(candidate, "experience")["entries"].reverse()

    finalized = finalize_ai_resume(source, candidate)

    assert [entry["period"] for entry in _entries(finalized)] == [
        "Apr 2021 - Dec 2023",
        "Jan 2020 - Mar 2021",
    ]
    assert validate_confirmed_resume(source, finalized) == []


async def test_refiner_rolls_back_malformed_writer_output() -> None:
    source = _source_document()
    master = copy.deepcopy(source)
    _values(master).append("Kubernetes")
    malformed = copy.deepcopy(source)
    _section(malformed, "skills")["groups"] = None

    with patch(
        "app.services.refiner.complete_json",
        new_callable=AsyncMock,
        return_value=malformed,
    ):
        result = await refine_resume(
            source,
            master,
            "Kubernetes role",
            {"required_skills": ["Kubernetes"]},
            RefinementConfig(
                enable_keyword_injection=True,
                enable_ai_phrase_removal=False,
                enable_master_alignment_check=False,
            ),
        )

    assert result.refined_data == source


def test_ats_score_uses_post_preservation_resume_match() -> None:
    ats_payload = {
        "overall_score": 25.0,
        "sub_scores": {
            "keyword_match": 25.0,
            "experience_alignment": 0.0,
            "skills_coverage": 0.0,
            "education_fit": 0.0,
            "format_quality": 0.0,
        },
        "missing_keywords": [],
        "injectable_keywords": [],
        "recommendations": [],
    }
    with (
        patch("app.routers.resumes.calculate_keyword_match", return_value=25.0),
        patch("app.routers.resumes.compute_ats_score", return_value=ats_payload) as score,
    ):
        resumes._build_ats_score(
            _source_document(),
            {"keywords": ["Python"]},
            SimpleNamespace(
                final_match_percentage=99.0,
                keyword_analysis=None,
            ),
            True,
        )

    assert score.call_args.kwargs["keyword_match_percentage"] == 25.0


def test_weakly_grounded_narrative_gets_stable_review_warning() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    _bullets(candidate)[0]["text"] = "Owned moon missions"

    warnings = grounding_review_warnings(source, candidate)

    assert warnings == [
        f"{GROUNDING_REVIEW_CODE}: Review "
        "sections.experience.entries[0].bullets[0] against the source resume."
    ]


def test_user_created_section_claims_use_the_same_grounding_policy() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    _bullets(candidate, "talks")[0]["text"] = "Commanded lunar expeditions"

    warnings = grounding_review_warnings(source, candidate)

    assert warnings == [
        f"{GROUNDING_REVIEW_CODE}: Review "
        "sections.talks.entries[0].bullets[0] against the source resume."
    ]


def test_weakly_grounded_text_section_rewrite_is_flagged() -> None:
    source = _source_document()
    candidate = copy.deepcopy(source)
    _section(candidate, "summary")["text"] = "Astronaut and lunar mission commander."

    warnings = grounding_review_warnings(source, candidate)

    assert warnings == [
        f"{GROUNDING_REVIEW_CODE}: Review sections.summary.text "
        "against the source resume."
    ]


# --- date restoration (parser) --------------------------------------------


def _dated_document(entries: list[tuple[str, str, str, str]]) -> dict[str, Any]:
    """A document whose entries carry (section key, title, subtitle, period)."""
    sections: dict[str, dict[str, Any]] = {}
    for key, title, subtitle, period in entries:
        section = sections.setdefault(
            key,
            {
                "id": f"s-{key}",
                "key": key,
                "heading": key.title(),
                "kind": "entries",
                "entries": [],
            },
        )
        section["entries"].append(
            _entry(f"e-{title}-{period}", title, subtitle, period)
        )
    return {
        "schemaVersion": 2,
        "header": {"name": "Ada Lovelace"},
        "sections": list(sections.values()),
    }


def test_date_restoration_matches_same_year_roles_by_context() -> None:
    parsed = _dated_document(
        [
            ("experience", "Engineer", "Alpha", "2020 - 2021"),
            ("experience", "Lead", "Beta", "2020 - 2021"),
        ]
    )
    markdown = """## Experience
Engineer — Alpha | Jan 2020 - Mar 2021
Lead — Beta | Apr 2020 - Dec 2021
"""

    result = restore_dates_from_markdown(parsed, markdown)

    assert [entry["period"] for entry in _entries(result)] == [
        "Jan 2020 - Mar 2021",
        "Apr 2020 - Dec 2021",
    ]


def test_date_restoration_uses_nearby_identity_for_date_only_lines() -> None:
    parsed = _dated_document(
        [
            ("experience", "Engineer", "Alpha", "2020 - 2021"),
            ("experience", "Lead", "Beta", "2020 - 2021"),
        ]
    )
    markdown = """Engineer — Alpha
Jan 2020 - Mar 2021
Lead — Beta
Apr 2020 - Dec 2021
"""

    result = restore_dates_from_markdown(parsed, markdown)

    assert [entry["period"] for entry in _entries(result)] == [
        "Jan 2020 - Mar 2021",
        "Apr 2020 - Dec 2021",
    ]


def test_date_restoration_preserves_ambiguous_collision() -> None:
    parsed = _dated_document([("experience", "Engineer", "", "2020 - 2021")])
    markdown = "Jan 2020 - Mar 2021\nApr 2020 - Dec 2021"

    result = restore_dates_from_markdown(parsed, markdown)

    assert _entries(result)[0]["period"] == "2020 - 2021"


def test_date_restoration_handles_present_current_and_cross_section_context() -> None:
    parsed = _dated_document(
        [
            ("experience", "Engineer", "Alpha", "2021 - Present"),
            ("projects", "Parser", "Maintainer", "2021 - Present"),
        ]
    )
    markdown = """Engineer — Alpha | Jan 2021 - Current
Parser — Maintainer | May 2021 - Present
"""

    result = restore_dates_from_markdown(parsed, markdown)

    assert _entries(result)[0]["period"] == "Jan 2021 - Current"
    assert _entries(result, "projects")[0]["period"] == "May 2021 - Present"


def test_full_month_name_is_already_precise() -> None:
    parsed = _dated_document(
        [("experience", "Engineer", "Alpha", "January 2020 - Current")]
    )

    result = restore_dates_from_markdown(parsed, "Alpha | Feb 2020 - Present")

    assert _entries(result)[0]["period"] == "January 2020 - Current"


def test_single_occurrence_requires_matching_identity_across_sections() -> None:
    parsed = _dated_document(
        [
            ("experience", "Research Intern", "Example University", "2020 - 2021"),
            ("education", "Example University", "BSc", "2020 - 2021"),
        ]
    )
    markdown = "## Education\nExample University — BSc\nJan 2020 - Dec 2021"

    result = restore_dates_from_markdown(parsed, markdown)

    assert _entries(result)[0]["period"] == "2020 - 2021"
    assert _entries(result, "education")[0]["period"] == "Jan 2020 - Dec 2021"


def test_single_year_range_and_wide_normalized_context_restore() -> None:
    parsed = _dated_document([("experience", "Engineer", "Alpha Labs", "2020")])
    markdown = """Engineer  —  Alpha Labs
- Built APIs
- Shipped services
- Mentored peers
Jan 2020 - Dec 2020
"""

    result = restore_dates_from_markdown(parsed, markdown)

    assert _entries(result)[0]["period"] == "Jan 2020 - Dec 2020"
