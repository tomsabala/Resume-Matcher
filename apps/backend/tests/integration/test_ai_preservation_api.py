"""Composed preview/confirm preservation and safe-warning regressions."""

import copy
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.document import ResumeDocument
from app.schemas.models import RefinementStats
from tests.integration.test_pipeline_e2e import _section, _upload_resume


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _document(sample_resume: dict[str, Any]) -> dict[str, Any]:
    """The fixture as the schema stores it, so payload comparisons are exact."""
    return ResumeDocument.model_validate(copy.deepcopy(sample_resume)).model_dump(
        mode="json"
    )


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


def _extra_section(key: str, heading: str, kind: str, **content: Any) -> dict[str, Any]:
    """A user-authored section — the v2 replacement for ``customSections``."""
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


async def _seed(isolated_db: Any, source: dict[str, Any]) -> tuple[str, str]:
    upload = await _upload_resume(isolated_db, source)
    resume_id = upload.json()["resume_id"]
    async with _client() as client:
        jobs = await client.post(
            "/api/v1/jobs/upload",
            json={
                "job_descriptions": [
                    "Backend Engineer at Example: Python and Kubernetes"
                ]
            },
        )
    return resume_id, jobs.json()["job_id"][0]


def _refinement_result(data: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        refined_data=data,
        passes_completed=1,
        ai_phrases_removed=[],
        keyword_analysis=None,
        final_match_percentage=50.0,
        alignment_report=SimpleNamespace(violations=[]),
        to_stats=lambda _initial: None,
    )


def _pipeline_patches(initial: dict[str, Any], refinement: object) -> tuple[Any, ...]:
    return (
        patch(
            "app.routers.resumes.extract_job_keywords",
            new_callable=AsyncMock,
            return_value={
                "keywords": ["Python"],
                "required_skills": ["Kubernetes"],
                "preferred_skills": [],
            },
        ),
        patch(
            "app.routers.resumes.generate_skill_target_plan",
            new_callable=AsyncMock,
            return_value={"accepted": [], "rejected": []},
        ),
        patch(
            "app.routers.resumes.verify_skill_target_plan",
            return_value={"accepted": [], "rejected": []},
        ),
        patch(
            "app.routers.resumes.generate_resume_diffs",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(changes=[]),
        ),
        patch(
            "app.routers.resumes.apply_diffs",
            return_value=(copy.deepcopy(initial), [], []),
        ),
        patch("app.routers.resumes.verify_diff_result", return_value=[]),
        patch(
            "app.routers.resumes.refine_resume",
            new_callable=AsyncMock,
            **(
                {"side_effect": refinement}
                if isinstance(refinement, Exception)
                else {"return_value": refinement}
            ),
        ),
        patch(
            "app.routers.resumes.generate_resume_title",
            new_callable=AsyncMock,
            return_value="Backend Engineer - Example",
        ),
    )


async def test_partial_final_writer_preview_confirms_and_reads_back_without_loss(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """A writer that returns only the sections it touched must lose nothing."""
    source = _document(sample_resume)
    _section(source, "experience")["entries"][0]["bullets"][0]["style"] = "plain"
    source["sections"].append(
        _extra_section(
            "talks",
            "Talks",
            "entries",
            entries=[
                _entry(
                    "e-pycon",
                    title="PyCon",
                    bullets=[{"text": "Spoke on testing", "style": "bullet"}],
                )
            ],
        )
    )
    resume_id, job_id = await _seed(isolated_db, source)
    initial = copy.deepcopy(source)
    _section(initial, "summary")["text"] = "Python backend engineer."
    partial = {
        "schemaVersion": 2,
        "header": copy.deepcopy(source["header"]),
        "sections": [
            {
                **copy.deepcopy(_section(source, "summary")),
                "text": "Python backend engineer for reliable systems.",
            }
        ],
    }
    preserved = ("experience", "education", "projects", "skills", "talks")

    with ExitStack() as stack:
        for pipeline_patch in _pipeline_patches(initial, _refinement_result(partial)):
            stack.enter_context(pipeline_patch)
        async with _client() as client:
            preview = await client.post(
                "/api/v1/resumes/improve/preview",
                json={"resume_id": resume_id, "job_id": job_id},
            )
        assert preview.status_code == 200, preview.text
        preview_data = preview.json()["data"]
        preview_resume = preview_data["resume_preview"]
        for key in preserved:
            assert _section(preview_resume, key) == _section(source, key)

        mutated = copy.deepcopy(preview_resume)
        _section(mutated, "experience")["entries"][0]["subtitle"] = "Moon Base"
        async with _client() as client:
            rejected = await client.post(
                "/api/v1/resumes/improve/confirm",
                json={
                    "resume_id": resume_id,
                    "job_id": job_id,
                    "preview_id": preview_data["preview_id"],
                    "improved_data": mutated,
                    "improvements": preview_data["improvements"],
                },
            )
        assert rejected.status_code == 400

        async with _client() as client:
            confirm = await client.post(
                "/api/v1/resumes/improve/confirm",
                json={
                    "resume_id": resume_id,
                    "job_id": job_id,
                    "preview_id": preview_data["preview_id"],
                    "improved_data": preview_resume,
                    "improvements": preview_data["improvements"],
                },
            )
        assert confirm.status_code == 200, confirm.text

    tailored_id = confirm.json()["data"]["resume_id"]
    stored = await isolated_db.get_resume(tailored_id)
    assert stored is not None
    for key in preserved:
        assert _section(stored["processed_data"], key) == _section(source, key)


async def test_schema_round_trip_preview_preserves_rows_styles_and_list_multiplicity(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """A destructive writer may not blank rows, drop styles or dedupe values."""
    source = _document(sample_resume)
    _section(source, "experience")["entries"][0]["bullets"][0]["style"] = "plain"
    _section(source, "skills")["groups"][0]["values"] = ["Python", "Python"]
    source["sections"].append(
        _extra_section(
            "talks",
            "Talks",
            "entries",
            entries=[
                _entry(
                    "e-pycon",
                    title="PyCon",
                    bullets=[{"text": "Spoke on testing", "style": "plain"}],
                )
            ],
        )
    )
    source["sections"].append(
        _extra_section("topics", "Topics", "tags", tags=["Reliability", "Reliability"])
    )
    destructive = copy.deepcopy(source)
    _section(destructive, "experience")["entries"][0]["bullets"] = [
        {"text": "   ", "style": "bullet"}
    ]
    _section(destructive, "talks")["entries"][0]["bullets"] = [
        {"text": "\t", "style": "bullet"}
    ]
    _section(destructive, "skills")["groups"] = []
    _section(destructive, "topics")["tags"] = []
    resume_id, job_id = await _seed(isolated_db, source)

    with ExitStack() as stack:
        for pipeline_patch in _pipeline_patches(
            source, _refinement_result(destructive)
        ):
            stack.enter_context(pipeline_patch)
        async with _client() as client:
            preview = await client.post(
                "/api/v1/resumes/improve/preview",
                json={"resume_id": resume_id, "job_id": job_id},
            )
            assert preview.status_code == 200, preview.text
            preview_data = preview.json()["data"]
            preview_resume = preview_data["resume_preview"]
            confirm = await client.post(
                "/api/v1/resumes/improve/confirm",
                json={
                    "resume_id": resume_id,
                    "job_id": job_id,
                    "preview_id": preview_data["preview_id"],
                    "improved_data": preview_resume,
                    "improvements": preview_data["improvements"],
                },
            )

    assert confirm.status_code == 200, confirm.text
    assert (
        _section(preview_resume, "experience")["entries"][0]["bullets"]
        == _section(source, "experience")["entries"][0]["bullets"]
    )
    assert _section(preview_resume, "skills")["groups"][0]["values"] == [
        "Python",
        "Python",
    ]
    assert _section(preview_resume, "talks") == _section(source, "talks")
    assert _section(preview_resume, "topics")["tags"] == ["Reliability", "Reliability"]
    tailored_id = confirm.json()["data"]["resume_id"]
    stored = await isolated_db.get_resume(tailored_id)
    assert stored is not None
    assert stored["processed_data"] == preview_resume


async def test_duplicate_identity_reorder_preview_confirms_without_false_drift(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """Two jobs with the same title and company must not swap their content."""
    source = _document(sample_resume)
    first = _entry(
        "e-first",
        title="Software Engineer",
        subtitle="Acme",
        period="2019 - 2020",
        bullets=[{"text": "Built Python APIs", "style": "bullet"}],
    )
    second = _entry(
        "e-second",
        title="Software Engineer",
        subtitle="Acme",
        period="2021 - 2023",
        bullets=[{"text": "Maintained data pipelines", "style": "bullet"}],
    )
    _section(source, "experience")["entries"] = [first, second]
    candidate = copy.deepcopy(source)
    _section(candidate, "experience")["entries"].reverse()
    resume_id, job_id = await _seed(isolated_db, source)

    with ExitStack() as stack:
        for pipeline_patch in _pipeline_patches(source, _refinement_result(candidate)):
            stack.enter_context(pipeline_patch)
        async with _client() as client:
            preview = await client.post(
                "/api/v1/resumes/improve/preview",
                json={"resume_id": resume_id, "job_id": job_id},
            )
            assert preview.status_code == 200, preview.text
            preview_data = preview.json()["data"]
            entries = _section(preview_data["resume_preview"], "experience")["entries"]
            # The reorder is adopted, and each row keeps its own period/bullets.
            assert [
                (entry["period"], [bullet["text"] for bullet in entry["bullets"]])
                for entry in entries
            ] == [
                ("2021 - 2023", ["Maintained data pipelines"]),
                ("2019 - 2020", ["Built Python APIs"]),
            ]

            confirm = await client.post(
                "/api/v1/resumes/improve/confirm",
                json={
                    "resume_id": resume_id,
                    "job_id": job_id,
                    "preview_id": preview_data["preview_id"],
                    "improved_data": preview_data["resume_preview"],
                    "improvements": preview_data["improvements"],
                },
            )

    assert confirm.status_code == 200, confirm.text


async def test_nested_preview_and_confirm_failures_return_only_safe_warning_codes(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    marker = "private-provider-marker-123"
    source = _document(sample_resume)
    resume_id, job_id = await _seed(isolated_db, source)

    patches = _pipeline_patches(source, RuntimeError(marker))
    with ExitStack() as stack:
        for pipeline_patch in patches:
            stack.enter_context(pipeline_patch)
        stack.enter_context(
            patch(
                "app.routers.resumes.diff_documents",
                side_effect=RuntimeError(marker),
            )
        )
        async with _client() as client:
            preview = await client.post(
                "/api/v1/resumes/improve/preview",
                json={"resume_id": resume_id, "job_id": job_id},
            )
        assert preview.status_code == 200, preview.text
        preview_data = preview.json()["data"]
        assert marker not in preview.text
        assert any(
            warning.startswith("REFINEMENT_FAILED:")
            for warning in preview_data["warnings"]
        )
        assert any(
            warning.startswith("DIFF_UNAVAILABLE:")
            for warning in preview_data["warnings"]
        )

        async with _client() as client:
            confirm = await client.post(
                "/api/v1/resumes/improve/confirm",
                json={
                    "resume_id": resume_id,
                    "job_id": job_id,
                    "preview_id": preview_data["preview_id"],
                    "improved_data": preview_data["resume_preview"],
                    "improvements": preview_data["improvements"],
                },
            )
        assert confirm.status_code == 200, confirm.text
        assert marker not in confirm.text
        assert any(
            warning.startswith("DIFF_UNAVAILABLE:")
            for warning in confirm.json()["data"]["warnings"]
        )


async def test_legacy_direct_improve_restores_unapproved_narrative_before_save(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    source = _document(sample_resume)
    _section(source, "experience")["entries"][0]["bullets"][0]["text"] = (
        "Built Python APIs"
    )
    candidate = copy.deepcopy(source)
    _section(candidate, "experience")["entries"][0]["bullets"][0]["text"] = (
        "Owned moon missions"
    )
    resume_id, job_id = await _seed(isolated_db, source)

    with ExitStack() as stack:
        for pipeline_patch in _pipeline_patches(source, _refinement_result(candidate)):
            stack.enter_context(pipeline_patch)
        async with _client() as client:
            response = await client.post(
                "/api/v1/resumes/improve",
                json={"resume_id": resume_id, "job_id": job_id},
            )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert _section(data["resume_preview"], "experience")["entries"][0]["bullets"][0][
        "text"
    ] == "Built Python APIs"
    assert not any(
        warning.startswith("GROUNDING_REVIEW_REQUIRED:") for warning in data["warnings"]
    )
    stored = await isolated_db.get_resume(data["resume_id"])
    assert stored is not None
    assert _section(stored["processed_data"], "experience")["entries"][0]["bullets"][0][
        "text"
    ] == "Built Python APIs"


async def test_preview_metrics_count_only_keywords_in_finalized_resume(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    source = _document(sample_resume)
    _section(source, "experience")["entries"][0]["bullets"][0]["text"] = (
        "Built Python APIs"
    )
    candidate = copy.deepcopy(source)
    _section(candidate, "experience")["entries"][0]["bullets"][0]["text"] = (
        "Improved throughput by 500%"
    )
    resume_id, job_id = await _seed(isolated_db, source)
    refinement = SimpleNamespace(
        refined_data=candidate,
        passes_completed=1,
        ai_phrases_removed=[],
        keyword_analysis=None,
        keywords_applied=["500%"],
        final_match_percentage=99.0,
        alignment_report=SimpleNamespace(violations=[]),
        to_stats=lambda initial: RefinementStats(
            passes_completed=1,
            passes_attempted=1,
            keywords_injected=1,
            initial_match_percentage=initial,
            final_match_percentage=99.0,
        ),
    )

    with ExitStack() as stack:
        for pipeline_patch in _pipeline_patches(source, refinement):
            stack.enter_context(pipeline_patch)
        async with _client() as client:
            response = await client.post(
                "/api/v1/resumes/improve/preview",
                json={"resume_id": resume_id, "job_id": job_id},
            )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert "500%" not in str(data["resume_preview"])
    assert data["refinement_stats"]["keywords_injected"] == 0
    assert data["refinement_stats"]["final_match_percentage"] != 99.0


async def test_preview_warning_allows_explicit_confirmation_of_narrative_rewrite(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    source = _document(sample_resume)
    _section(source, "experience")["entries"][0]["bullets"][0]["text"] = (
        "Built Python APIs"
    )
    candidate = copy.deepcopy(source)
    _section(candidate, "experience")["entries"][0]["bullets"][0]["text"] = (
        "Owned moon missions"
    )
    resume_id, job_id = await _seed(isolated_db, source)

    with ExitStack() as stack:
        for pipeline_patch in _pipeline_patches(source, _refinement_result(candidate)):
            stack.enter_context(pipeline_patch)
        async with _client() as client:
            preview = await client.post(
                "/api/v1/resumes/improve/preview",
                json={"resume_id": resume_id, "job_id": job_id},
            )
            assert preview.status_code == 200, preview.text
            preview_data = preview.json()["data"]
            assert any(
                warning.startswith("GROUNDING_REVIEW_REQUIRED:")
                for warning in preview_data["warnings"]
            )
            assert _section(preview_data["resume_preview"], "experience")["entries"][0][
                "bullets"
            ][0]["text"] == "Owned moon missions"

            confirm = await client.post(
                "/api/v1/resumes/improve/confirm",
                json={
                    "resume_id": resume_id,
                    "job_id": job_id,
                    "preview_id": preview_data["preview_id"],
                    "improved_data": preview_data["resume_preview"],
                    "improvements": preview_data["improvements"],
                },
            )

    assert confirm.status_code == 200, confirm.text
    confirm_data = confirm.json()["data"]
    assert any(
        warning.startswith("GROUNDING_REVIEW_REQUIRED:")
        for warning in confirm_data["warnings"]
    )
    stored = await isolated_db.get_resume(confirm_data["resume_id"])
    assert stored is not None
    assert _section(stored["processed_data"], "experience")["entries"][0]["bullets"][0][
        "text"
    ] == "Owned moon missions"
