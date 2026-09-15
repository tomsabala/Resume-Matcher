"""Offline tests for the scorer-runner (reuses tests/evals/scorers.py)."""

from __future__ import annotations

import copy
from typing import Any

from e2e_monitor.flow import score_tailoring


def _section(document: dict[str, Any], key: str) -> dict[str, Any]:
    return next(section for section in document["sections"] if section["key"] == key)


def test_score_tailoring_clean_pass(sample_resume: dict[str, Any]) -> None:
    tailored = copy.deepcopy(sample_resume)
    _section(tailored, "experience")["entries"][0]["bullets"] = [
        {"text": "Built Python APIs serving 50K requests/day", "style": "bullet"}
    ]
    scores = score_tailoring(sample_resume, tailored, keywords=["python"])
    assert scores["sections_preserved"] is True
    assert scores["fabricated_entries"] == []
    assert scores["header_unchanged"] is True
    assert scores["is_valid_resume"] is True
    assert scores["jd_keyword_coverage"] == 1.0


def test_score_tailoring_flags_fabrication_and_identity_change(
    sample_resume: dict[str, Any],
) -> None:
    tailored = copy.deepcopy(sample_resume)
    tailored["header"]["name"] = "CHANGED"
    _section(tailored, "experience")["entries"][0]["subtitle"] = "FakeCorp"
    scores = score_tailoring(sample_resume, tailored, keywords=["kubernetes"])
    assert scores["fabricated_entries"] == ["Senior Backend Engineer — FakeCorp"]
    assert scores["header_unchanged"] is False
    assert scores["jd_keyword_coverage"] == 0.0


def test_score_tailoring_flags_a_dropped_section(
    sample_resume: dict[str, Any],
) -> None:
    """Emptying a populated section must trip the preservation scorer."""
    tailored = copy.deepcopy(sample_resume)
    tailored["sections"] = [
        section for section in tailored["sections"] if section["key"] != "education"
    ]
    scores = score_tailoring(sample_resume, tailored, keywords=["python"])
    assert scores["sections_preserved"] is False
    assert scores["fabricated_entries"] == []
