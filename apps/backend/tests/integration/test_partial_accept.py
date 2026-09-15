"""Partial accept: confirming a subset of an AI proposal.

The tailoring preview is all-or-nothing without this; the user either takes
every rewrite or none. ``accepted_paths`` lets them take the good ones.
"""

import copy
from contextlib import ExitStack
from typing import Any

import pytest

from tests.integration.test_ai_preservation_api import (
    _client,
    _document,
    _pipeline_patches,
    _refinement_result,
    _seed,
)
from tests.integration.test_pipeline_e2e import _section

pytestmark = pytest.mark.integration


# Suffixes deliberately contain no digits: the preservation layer restores any
# rewrite that introduces a number the source never had, which would make the
# fixture, not the code, decide the outcome.
_REWRITES = (" and Terraform", " end to end", " across teams", " with tracing")


def _rewrite_bullets(document: dict[str, Any], count: int) -> dict[str, Any]:
    """Reword the first ``count`` bullets of the experience section."""
    proposal = copy.deepcopy(document)
    section = _section(proposal, "experience")
    rewritten = 0
    for entry in section["entries"]:
        for bullet in entry["bullets"]:
            if rewritten >= count:
                return proposal
            bullet["text"] = f"{bullet['text']}{_REWRITES[rewritten]}"
            rewritten += 1
    return proposal


def _bullet_texts(document: dict[str, Any]) -> list[str]:
    return [
        bullet["text"]
        for entry in _section(document, "experience")["entries"]
        for bullet in entry["bullets"]
    ]


async def _preview(isolated_db: Any, source: dict[str, Any], proposal: dict[str, Any]):
    """Run a preview whose AI stage returns ``proposal``."""
    resume_id, job_id = await _seed(isolated_db, source)
    with ExitStack() as stack:
        for pipeline_patch in _pipeline_patches(
            proposal, _refinement_result(copy.deepcopy(proposal))
        ):
            stack.enter_context(pipeline_patch)
        async with _client() as client:
            response = await client.post(
                "/api/v1/resumes/improve/preview",
                json={"resume_id": resume_id, "job_id": job_id},
            )
    assert response.status_code == 200, response.text
    return resume_id, job_id, response.json()["data"]


async def _confirm(
    resume_id: str,
    job_id: str,
    preview: dict[str, Any],
    accepted_paths: list[str] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "resume_id": resume_id,
        "job_id": job_id,
        "preview_id": preview["preview_id"],
        "improved_data": preview["resume_preview"],
        "improvements": preview["improvements"],
    }
    if accepted_paths is not None:
        payload["accepted_paths"] = accepted_paths
    async with _client() as client:
        response = await client.post("/api/v1/resumes/improve/confirm", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_the_preview_carries_a_structured_diff(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    source = _document(sample_resume)
    proposal = _rewrite_bullets(source, 4)

    _, _, preview = await _preview(isolated_db, source, proposal)

    diff = preview["diff"]
    assert diff is not None
    assert diff["stats"]["bullets_modified"] == 4
    modified = [
        row
        for section in diff["sections"]
        for row in section["rows"]
        if row["status"] == "modified"
    ]
    assert len(modified) == 4
    # Every modified row must be individually addressable, or the user cannot
    # tick it.
    assert all(row["path"].endswith(".text") for row in modified)
    assert all(row["spans"] for row in modified)


async def test_confirming_a_subset_takes_exactly_those_changes(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    source = _document(sample_resume)
    proposal = _rewrite_bullets(source, 4)
    resume_id, job_id, preview = await _preview(isolated_db, source, proposal)

    modified = [
        row
        for section in preview["diff"]["sections"]
        for row in section["rows"]
        if row["status"] == "modified"
    ]
    accepted = [row["path"] for row in modified[:2]]

    data = await _confirm(resume_id, job_id, preview, accepted)
    saved = await isolated_db.get_resume(data["resume_id"])
    texts = _bullet_texts(saved["processed_data"])

    rewritten = [text for text in texts if any(s in text for s in _REWRITES)]
    assert len(rewritten) == 2
    # And they are the two the user ticked, not just any two.
    expected = {row["head_text"] for row in modified[:2]}
    assert set(rewritten) == expected
    # The rest stayed exactly as the source had them.
    assert set(_bullet_texts(source)) - set(texts) == {
        row["base_text"] for row in modified[:2]
    }


async def test_accepting_nothing_saves_the_original_content(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    source = _document(sample_resume)
    proposal = _rewrite_bullets(source, 3)
    resume_id, job_id, preview = await _preview(isolated_db, source, proposal)

    data = await _confirm(resume_id, job_id, preview, [])
    saved = await isolated_db.get_resume(data["resume_id"])

    assert _bullet_texts(saved["processed_data"]) == _bullet_texts(source)


async def test_omitting_accepted_paths_still_takes_the_whole_preview(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """The pre-partial-accept behaviour stays the default."""
    source = _document(sample_resume)
    proposal = _rewrite_bullets(source, 3)
    resume_id, job_id, preview = await _preview(isolated_db, source, proposal)

    data = await _confirm(resume_id, job_id, preview, None)
    saved = await isolated_db.get_resume(data["resume_id"])

    assert _bullet_texts(saved["processed_data"]) == _bullet_texts(proposal)
