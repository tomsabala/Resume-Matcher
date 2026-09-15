"""Unit tests for verify_diff_result() — local quality checks."""

import copy
from typing import Any

import pytest

from app.schemas.models import ResumeChange
from app.services.improver import verify_diff_result

SUMMARY = "sections.summary.text"


def _section(document: dict[str, Any], key: str) -> dict[str, Any]:
    return next(section for section in document["sections"] if section["key"] == key)


def _entries(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return _section(document, key)["entries"]


def _bullets(document: dict[str, Any], key: str, entry: int) -> list[dict[str, Any]]:
    return _entries(document, key)[entry]["bullets"]


def _bullet_rows(*texts: str) -> list[dict[str, Any]]:
    return [{"text": text, "style": "bullet"} for text in texts]


@pytest.fixture
def summary_change(sample_resume) -> ResumeChange:
    """A minimal applied change, so the early-return check is satisfied."""
    return ResumeChange(
        path=SUMMARY,
        action="replace",
        original=_section(sample_resume, "summary")["text"],
        value="Changed.",
        reason="test",
    )


class TestVerifyNoWarnings:
    """Tests that pass cleanly with no warnings."""

    def test_clean_result_no_warnings(
        self, sample_resume, sample_job_keywords, summary_change
    ):
        result = copy.deepcopy(sample_resume)
        _section(result, "summary")["text"] = "Changed."
        warnings = verify_diff_result(
            sample_resume, result, [summary_change], sample_job_keywords
        )
        assert warnings == []


class TestVerifyEmptyChanges:
    """Check 1: No changes applied."""

    def test_warns_on_empty_applied_changes(self, sample_resume, sample_job_keywords):
        warnings = verify_diff_result(sample_resume, sample_resume, [], sample_job_keywords)
        assert len(warnings) == 1
        assert "no changes" in warnings[0].lower()

    def test_returns_early_on_empty(self, sample_resume, sample_job_keywords):
        """When no changes applied, skip other checks."""
        broken = copy.deepcopy(sample_resume)
        _entries(broken, "experience").clear()
        warnings = verify_diff_result(sample_resume, broken, [], sample_job_keywords)
        # Only the "no changes" warning — the dropped section is never inspected.
        assert len(warnings) == 1


class TestVerifyEntryCounts:
    """Check 2: Entry counts preserved, per ENTRIES section."""

    @pytest.mark.parametrize(
        ("key", "heading"),
        [
            ("experience", "experience"),
            ("education", "education"),
            ("projects", "projects"),
        ],
    )
    def test_warns_on_dropped_entries(
        self, sample_resume, sample_job_keywords, summary_change, key, heading
    ):
        result = copy.deepcopy(sample_resume)
        _entries(result, key).clear()
        warnings = verify_diff_result(
            sample_resume, result, [summary_change], sample_job_keywords
        )
        assert any(
            "section count changed" in w.lower() and heading in w.lower()
            for w in warnings
        )

    def test_warns_on_dropped_user_created_section(
        self, sample_resume, sample_job_keywords, summary_change
    ):
        """A user-created ENTRIES section is checked like any built-in one."""
        source = copy.deepcopy(sample_resume)
        source["sections"].append(
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
                        "meta": "",
                        "period": "2012 - 2014",
                        "links": [],
                        "summary": "",
                        "bullets": _bullet_rows("Maintained field radio networks"),
                    }
                ],
                "tags": [],
                "groups": [],
            }
        )
        result = copy.deepcopy(source)
        _entries(result, "military_service").clear()
        warnings = verify_diff_result(
            source, result, [summary_change], sample_job_keywords
        )
        assert any("military service" in w.lower() for w in warnings)

    def test_no_warning_when_counts_match(
        self, sample_resume, sample_job_keywords, summary_change
    ):
        result = copy.deepcopy(sample_resume)
        _section(result, "summary")["text"] = "Changed."
        warnings = verify_diff_result(
            sample_resume, result, [summary_change], sample_job_keywords
        )
        assert [w for w in warnings if "section count" in w.lower()] == []


class TestVerifyIdentityFields:
    """Check 3: entry identity — (title, subtitle) — unchanged."""

    @pytest.mark.parametrize(
        ("key", "field", "value"),
        [
            ("experience", "subtitle", "Different Corp"),
            ("experience", "title", "VP of Engineering"),
            ("education", "title", "Stanford"),
            ("education", "subtitle", "PhD Computer Science"),
            ("projects", "title", "Some Other Tool"),
        ],
    )
    def test_warns_on_identity_change(
        self, sample_resume, sample_job_keywords, summary_change, key, field, value
    ):
        result = copy.deepcopy(sample_resume)
        _entries(result, key)[0][field] = value
        warnings = verify_diff_result(
            sample_resume, result, [summary_change], sample_job_keywords
        )
        assert any(
            w.startswith(f"Identity field changed: sections.{key}.entries[0].{field}")
            for w in warnings
        )

    def test_no_warning_when_only_prose_changed(
        self, sample_resume, sample_job_keywords, summary_change
    ):
        """Rewriting a bullet is the whole point of tailoring — not an identity change."""
        result = copy.deepcopy(sample_resume)
        _bullets(result, "experience", 0)[0]["text"] = "Built REST APIs with FastAPI"
        warnings = verify_diff_result(
            sample_resume, result, [summary_change], sample_job_keywords
        )
        assert [w for w in warnings if "identity" in w.lower()] == []


class TestVerifyWordCount:
    """Check 4: Word count ratio over prose (TEXT, entry summaries, bullets)."""

    def test_warns_on_word_count_explosion(
        self, sample_resume, sample_job_keywords, summary_change
    ):
        result = copy.deepcopy(sample_resume)
        long_text = "word " * 200
        for entry in range(2):
            _entries(result, "experience")[entry]["bullets"] = _bullet_rows(
                *[long_text] * 5
            )
        warnings = verify_diff_result(
            sample_resume, result, [summary_change], sample_job_keywords
        )
        assert any("word count" in w.lower() for w in warnings)

    def test_no_warning_on_normal_growth(self, sample_resume, sample_job_keywords):
        result = copy.deepcopy(sample_resume)
        _bullets(result, "experience", 0).append(
            {"text": "One extra bullet point here", "style": "bullet"}
        )
        applied = [
            ResumeChange(
                path="sections.experience.entries[0].bullets",
                action="append",
                original=None,
                value="One extra bullet point here",
                reason="z",
            )
        ]
        warnings = verify_diff_result(
            sample_resume, result, applied, sample_job_keywords
        )
        assert [w for w in warnings if "word count" in w.lower()] == []

    def test_short_values_do_not_count_as_prose(
        self, sample_resume, sample_job_keywords, summary_change
    ):
        """Only what the AI rewrites is measured: a huge skill list is not prose."""
        result = copy.deepcopy(sample_resume)
        _section(result, "skills")["groups"][0]["values"] = [
            f"Skill {index}" for index in range(300)
        ]
        warnings = verify_diff_result(
            sample_resume, result, [summary_change], sample_job_keywords
        )
        assert [w for w in warnings if "word count" in w.lower()] == []


class TestVerifyInventedMetrics:
    """Check 5: Invented metrics detection."""

    def test_warns_on_invented_percentage(self, sample_resume, sample_job_keywords):
        original = _bullets(sample_resume, "experience", 0)[1]["text"]
        applied = [
            ResumeChange(
                path="sections.experience.entries[0].bullets[1].text",
                action="replace",
                original=original,
                value="Led migration to microservices improving throughput by 40%",
                reason="Added metric",
            )
        ]
        result = copy.deepcopy(sample_resume)
        _bullets(result, "experience", 0)[1]["text"] = applied[0].value
        warnings = verify_diff_result(
            sample_resume, result, applied, sample_job_keywords
        )
        assert any("40%" in w for w in warnings)

    def test_no_warning_on_preserved_metric(self, sample_resume, sample_job_keywords):
        """If the original already had the metric, no warning."""
        applied = [
            ResumeChange(
                path="sections.experience.entries[0].bullets[0].text",
                action="replace",
                original="Built REST APIs serving 50K requests/day using Python and FastAPI",
                value="Designed REST APIs serving 50K requests/day with Python and FastAPI",
                reason="Rephrased",
            )
        ]
        result = copy.deepcopy(sample_resume)
        _bullets(result, "experience", 0)[0]["text"] = applied[0].value
        warnings = verify_diff_result(
            sample_resume, result, applied, sample_job_keywords
        )
        assert [w for w in warnings if "metric" in w.lower()] == []

    def test_warns_on_invented_dollar_amount(self, sample_resume, sample_job_keywords):
        applied = [
            ResumeChange(
                path="sections.experience.entries[1].bullets[0].text",
                action="replace",
                original="Developed payment processing system handling $2M monthly",
                value="Developed payment processing system handling $5M monthly",
                reason="Inflated",
            )
        ]
        result = copy.deepcopy(sample_resume)
        _bullets(result, "experience", 1)[0]["text"] = applied[0].value
        warnings = verify_diff_result(
            sample_resume, result, applied, sample_job_keywords
        )
        # The metric regex captures `$<digits>`, so the inflated claim is "$5".
        assert any("Possible invented metric" in w and "$5" in w for w in warnings)

    def test_warns_on_metric_in_appended_bullet(
        self, sample_resume, sample_job_keywords
    ):
        """An append has no `original`, so any metric in it is unverified."""
        value = "Cut infrastructure spend by 30%"
        applied = [
            ResumeChange(
                path="sections.experience.entries[0].bullets",
                action="append",
                original=None,
                value=value,
                reason="test",
            )
        ]
        result = copy.deepcopy(sample_resume)
        _bullets(result, "experience", 0).append({"text": value, "style": "bullet"})
        warnings = verify_diff_result(
            sample_resume, result, applied, sample_job_keywords
        )
        assert any("30%" in w for w in warnings)


class TestVerifyMultipleWarnings:
    """Edge case: multiple warnings from a single verification run."""

    def test_multiple_warnings_all_reported(
        self, sample_resume, sample_job_keywords, summary_change
    ):
        """Entry-count drift AND an identity change must both be reported."""
        result = copy.deepcopy(sample_resume)
        del _entries(result, "experience")[1]
        _entries(result, "experience")[0]["subtitle"] = "Different Corp"
        warnings = verify_diff_result(
            sample_resume, result, [summary_change], sample_job_keywords
        )
        assert any("section count changed" in w.lower() for w in warnings)
        assert any("identity field changed" in w.lower() for w in warnings)
        assert len(warnings) >= 2

    def test_metric_warning_plus_word_count_warning(
        self, sample_resume, sample_job_keywords
    ):
        """Invented metric and word count explosion in the same result."""
        long_text = "Improved revenue by 99% " + ("extra words " * 200)
        result = copy.deepcopy(sample_resume)
        for entry in range(2):
            _entries(result, "experience")[entry]["bullets"] = _bullet_rows(
                *[long_text] * 5
            )
        applied = [
            ResumeChange(
                path="sections.experience.entries[0].bullets[0].text",
                action="replace",
                original="Built REST APIs serving 50K requests/day using Python and FastAPI",
                value=long_text,
                reason="over-elaborate",
            )
        ]
        warnings = verify_diff_result(
            sample_resume, result, applied, sample_job_keywords
        )
        assert any("99%" in w for w in warnings)
        assert any("word count" in w.lower() for w in warnings)
