"""Unit tests for refiner pure functions — no LLM calls needed."""

import copy
from collections.abc import Sequence
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.refiner import (
    _restore_bullet_styles,
    analyze_keyword_gaps,
    calculate_keyword_match,
    count_retained_keywords,
    fix_alignment_violations,
    refine_resume,
    remove_ai_phrases,
    validate_master_alignment,
)
from app.schemas.refinement import AlignmentViolation, RefinementConfig


# --- v2 document helpers ---------------------------------------------------


def _section(document: dict[str, Any], key: str) -> dict[str, Any]:
    return next(section for section in document["sections"] if section["key"] == key)


def _text(document: dict[str, Any], key: str = "summary") -> str:
    return _section(document, key)["text"]


def _set_text(document: dict[str, Any], text: str, key: str = "summary") -> None:
    _section(document, key)["text"] = text


def _values(
    document: dict[str, Any], label: str = "Technical Skills"
) -> list[str]:
    groups = _section(document, "skills")["groups"]
    return next(group for group in groups if group["label"] == label)["values"]


def _bullets(
    document: dict[str, Any], key: str = "experience", entry: int = 0
) -> list[dict[str, Any]]:
    return _section(document, key)["entries"][entry]["bullets"]


def _styles(
    document: dict[str, Any], key: str = "experience", entry: int = 0
) -> list[str]:
    return [bullet["style"] for bullet in _bullets(document, key, entry)]


def _document(
    summary: str = "",
    bullets: Sequence[tuple[str, str]] = (),
    *,
    key: str = "experience",
    heading: str = "Experience",
) -> dict[str, Any]:
    """A minimal but schema-valid document: one TEXT and one ENTRIES section."""
    return {
        "schemaVersion": 2,
        "header": {"name": "Jane Doe"},
        "sections": [
            {
                "id": "s-summary",
                "key": "summary",
                "heading": "Summary",
                "kind": "text",
                "text": summary,
            },
            {
                "id": f"s-{key}",
                "key": key,
                "heading": heading,
                "kind": "entries",
                "entries": [
                    {
                        "id": "e-1",
                        "title": "Engineer",
                        "subtitle": "Acme",
                        "period": "2020 - 2022",
                        "bullets": [
                            {"text": text, "style": style} for text, style in bullets
                        ],
                    }
                ],
            },
        ],
    }


def test_retained_keywords_use_cjk_substrings_and_latin_term_boundaries() -> None:
    resume = _document("负责数据分析与Pythonによる開発，熟悉Java开发与JavaScript平台")

    assert count_retained_keywords(
        ["数据", "Python", "Java", "JavaScript"], resume
    ) == 4
    assert count_retained_keywords(
        ["Java", "JavaScript"], _document("负责JavaScript平台开发")
    ) == 1


async def test_refinement_stats_count_retained_cjk_keyword(
    sample_resume: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    initial = copy.deepcopy(sample_resume)
    master = copy.deepcopy(initial)
    _values(master).append("数据分析")
    injected = copy.deepcopy(initial)
    _values(injected).append("数据分析")
    complete = AsyncMock(return_value=injected)
    monkeypatch.setattr("app.services.refiner.complete_json", complete)

    result = await refine_resume(
        initial_tailored=initial,
        master_resume=master,
        job_description="需要数据分析经验",
        job_keywords={"required_skills": ["数据"]},
        config=RefinementConfig(
            enable_ai_phrase_removal=False,
            enable_master_alignment_check=False,
        ),
    )

    assert result.keywords_applied == ["数据"]
    assert result.to_stats().keywords_injected == 1
    assert result.final_match_percentage == 100.0
    complete.assert_awaited_once()


@pytest.mark.parametrize(
    "summary", ["熟悉Java开发", "𠀀Java𰀀", "개발Java개발", "ᄀJavaᄂ"]
)
async def test_refinement_stats_count_latin_keyword_adjacent_to_cjk(
    sample_resume: dict[str, Any], monkeypatch: pytest.MonkeyPatch, summary: str
) -> None:
    initial = copy.deepcopy(sample_resume)
    master = copy.deepcopy(initial)
    _set_text(master, summary)
    injected = copy.deepcopy(initial)
    _set_text(injected, summary)
    complete = AsyncMock(return_value=injected)
    monkeypatch.setattr("app.services.refiner.complete_json", complete)

    result = await refine_resume(
        initial_tailored=initial,
        master_resume=master,
        job_description="需要熟悉Java开发",
        job_keywords={"required_skills": ["Java"]},
        config=RefinementConfig(
            enable_ai_phrase_removal=False,
            enable_master_alignment_check=False,
        ),
    )

    assert result.keywords_applied == ["Java"]
    assert result.to_stats().keywords_injected == 1
    assert result.final_match_percentage == 100.0
    complete.assert_awaited_once()


@pytest.mark.parametrize(
    "summary", ["𠀀JavaScript𰀀", "개발JavaScript개발", "ᄀJavaScriptᄂ"]
)
def test_cjk_boundaries_do_not_split_latin_terms(summary: str) -> None:
    assert count_retained_keywords(["Java"], _document(summary)) == 0


class TestRemoveAiPhrases:
    """Tests for remove_ai_phrases() — local regex replacement."""

    def test_removes_blacklisted_verbs(self, sample_resume):
        data = copy.deepcopy(sample_resume)
        _bullets(data)[0]["text"] = "Spearheaded REST API development"
        cleaned, removed = remove_ai_phrases(data)
        assert "spearheaded" in [r.lower() for r in removed]
        assert "spearheaded" not in _bullets(cleaned)[0]["text"].lower()

    def test_removes_buzzwords(self, sample_resume):
        data = copy.deepcopy(sample_resume)
        _set_text(data, "Leveraged cutting-edge technologies to build robust solutions")
        cleaned, removed = remove_ai_phrases(data)
        removed_lower = [r.lower() for r in removed]
        assert "leveraged" in removed_lower
        assert "cutting-edge" in removed_lower

    def test_protects_jd_phrases(self, sample_resume):
        data = copy.deepcopy(sample_resume)
        _set_text(data, "Built robust microservices")
        # "robust" is in the blacklist, but if it's in JD, it should be protected
        cleaned, removed = remove_ai_phrases(data, job_description="We need robust solutions")
        assert "robust" not in [r.lower() for r in removed]
        assert "robust" in _text(cleaned).lower()

    def test_replaces_with_alternatives(self, sample_resume):
        data = copy.deepcopy(sample_resume)
        _bullets(data)[0]["text"] = "Utilized Python for API development"
        cleaned, removed = remove_ai_phrases(data)
        # "utilized" → "used"
        assert "used" in _bullets(cleaned)[0]["text"].lower()

    def test_removes_em_dashes(self, sample_resume):
        data = copy.deepcopy(sample_resume)
        _set_text(data, "Built APIs \u2014 serving thousands of users")
        cleaned, removed = remove_ai_phrases(data)
        assert "\u2014" not in _text(cleaned)

    def test_no_removal_when_already_clean(self):
        """A resume with no blacklisted terms should have zero removals."""
        clean_data = _document(
            "Built APIs with Python.", [("Wrote code and shipped features", "bullet")]
        )
        cleaned, removed = remove_ai_phrases(clean_data)
        assert removed == []
        assert cleaned == clean_data

    def test_preserves_bullet_styles(self):
        """Cleaning text must not disturb the per-bullet style flags."""
        data = _document("", [("Spearheaded the rollout", "plain"), ("Shipped it", "bullet")])
        cleaned, _removed = remove_ai_phrases(data)
        assert _styles(cleaned) == ["plain", "bullet"]

    def test_does_not_mutate_input(self, sample_resume):
        data = copy.deepcopy(sample_resume)
        _set_text(data, "Spearheaded development")
        data_before = copy.deepcopy(data)
        remove_ai_phrases(data)
        # The input dict should not be mutated by remove_ai_phrases
        assert data == data_before


class TestValidateMasterAlignment:
    """Tests for validate_master_alignment() — fabrication detection."""

    def test_aligned_when_identical(self, sample_resume, master_resume):
        report = validate_master_alignment(sample_resume, master_resume)
        assert report.is_aligned is True
        assert len(report.violations) == 0

    def test_detects_fabricated_skill(self, sample_resume, master_resume):
        tailored = copy.deepcopy(sample_resume)
        _values(tailored).append("Kubernetes")
        report = validate_master_alignment(tailored, master_resume)
        skill_violations = [v for v in report.violations if "skill" in v.violation_type]
        assert len(skill_violations) >= 1
        assert any("kubernetes" in v.value.lower() for v in skill_violations)
        assert report.is_aligned is False

    def test_allows_jd_added_skill_when_explicitly_allowed(self, sample_resume, master_resume):
        tailored = copy.deepcopy(sample_resume)
        _values(tailored).append("Kubernetes")
        report = validate_master_alignment(
            tailored,
            master_resume,
            allowed_new_skills={"Kubernetes"},
        )
        critical_skill_violations = [
            v
            for v in report.violations
            if "skill" in v.violation_type and v.severity == "critical"
        ]
        assert critical_skill_violations == []

    async def test_refiner_rejects_skill_from_generic_keyword_only(
        self,
        sample_resume,
        master_resume,
    ):
        tailored = copy.deepcopy(sample_resume)
        _values(tailored).append("CI/CD")
        result = await refine_resume(
            initial_tailored=tailored,
            master_resume=master_resume,
            job_description="Familiarity with CI/CD pipelines and agile practices",
            job_keywords={
                "required_skills": [],
                "preferred_skills": [],
                "keywords": ["CI/CD"],
            },
            config=RefinementConfig(
                enable_keyword_injection=False,
                enable_ai_phrase_removal=False,
                enable_master_alignment_check=True,
            ),
        )
        assert "CI/CD" not in _values(result.refined_data)

    async def test_refiner_allows_required_skill_present_in_job_description(
        self,
        sample_resume,
        master_resume,
    ):
        tailored = copy.deepcopy(sample_resume)
        _values(tailored).append("Kubernetes")
        result = await refine_resume(
            initial_tailored=tailored,
            master_resume=master_resume,
            job_description="Experience with Kubernetes is required.",
            job_keywords={
                "required_skills": ["Kubernetes"],
                "preferred_skills": [],
                "keywords": [],
            },
            config=RefinementConfig(
                enable_keyword_injection=False,
                enable_ai_phrase_removal=False,
                enable_master_alignment_check=True,
            ),
        )
        assert "Kubernetes" in _values(result.refined_data)

    @pytest.mark.parametrize(
        ("skill", "job_description"),
        [
            ("C++", "Experience with C++ is required for systems tooling."),
            ("C#", "Experience with C# is required for .NET services."),
        ],
    )
    async def test_refiner_allows_required_punctuated_skill_present_in_job_description(
        self,
        sample_resume,
        master_resume,
        skill,
        job_description,
    ):
        tailored = copy.deepcopy(sample_resume)
        _values(tailored).append(skill)
        result = await refine_resume(
            initial_tailored=tailored,
            master_resume=master_resume,
            job_description=job_description,
            job_keywords={
                "required_skills": [skill],
                "preferred_skills": [],
                "keywords": [],
            },
            config=RefinementConfig(
                enable_keyword_injection=False,
                enable_ai_phrase_removal=False,
                enable_master_alignment_check=True,
            ),
        )
        assert skill in _values(result.refined_data)

    def test_detects_fabricated_certification(self, sample_resume, master_resume):
        """Certifications are short values in their own group — fabrication in a
        non-technical group is caught by the same check."""
        tailored = copy.deepcopy(sample_resume)
        _values(tailored, "Certifications & Training").append("Google Cloud Professional")
        report = validate_master_alignment(tailored, master_resume)
        critical = [
            v
            for v in report.violations
            if v.severity == "critical" and "google cloud" in v.value.lower()
        ]
        assert len(critical) == 1
        assert report.is_aligned is False

    def test_detects_fabricated_company(self, sample_resume, master_resume):
        tailored = copy.deepcopy(sample_resume)
        _section(tailored, "experience")["entries"].append(
            {
                "id": "e-fake",
                "title": "Engineer",
                "subtitle": "FakeCompany Inc",
                "period": "2015 - 2017",
                "bullets": [{"text": "Did things", "style": "bullet"}],
            }
        )
        report = validate_master_alignment(tailored, master_resume)
        company_violations = [
            v for v in report.violations if v.violation_type == "fabricated_company"
        ]
        assert len(company_violations) == 1
        assert company_violations[0].value == "fakecompany inc"
        assert company_violations[0].field_path == "sections.experience.entries"

    def test_detects_fabricated_entry_in_user_created_section(
        self, sample_resume, master_resume
    ):
        """Identity checks are section-agnostic: a user-created section's entries
        are validated like any built-in one."""
        tailored = copy.deepcopy(sample_resume)
        tailored["sections"].append(
            {
                "id": "s-military",
                "key": "military_service",
                "heading": "Military Service",
                "kind": "entries",
                "entries": [
                    {
                        "id": "e-signals",
                        "title": "Signals Officer",
                        "subtitle": "Invented Regiment",
                        "period": "2012 - 2014",
                    }
                ],
            }
        )
        report = validate_master_alignment(tailored, master_resume)
        assert any(
            v.violation_type == "fabricated_company"
            and v.field_path == "sections.military_service.entries"
            for v in report.violations
        )

    def test_allows_skill_variants_as_non_critical(self, sample_resume, master_resume):
        """A variant of an existing skill (e.g. 'Python 3') should be info, not critical."""
        tailored = copy.deepcopy(sample_resume)
        # Master has "Python", tailored adds "Python 3" — substring match should be non-critical
        _values(tailored).append("Python 3")
        report = validate_master_alignment(tailored, master_resume)
        python3_violations = [
            v for v in report.violations
            if "python 3" in v.value.lower()
        ]
        assert python3_violations
        # Should be info/variant, NOT critical fabricated_skill
        for v in python3_violations:
            assert v.severity != "critical" or v.violation_type == "skill_variant"

    def test_confidence_decreases_with_violations(self, sample_resume, master_resume):
        tailored = copy.deepcopy(sample_resume)
        _values(tailored).extend(["Kotlin", "Scala", "Haskell"])
        report = validate_master_alignment(tailored, master_resume)
        assert report.confidence_score < 1.0


class TestFixAlignmentViolations:
    """Tests for fix_alignment_violations() — removing fabricated content."""

    def test_removes_fabricated_skill(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        _values(tailored).append("FakeSkill")
        violations = [
            AlignmentViolation(
                field_path="sections.values",
                violation_type="fabricated_skill",
                value="FakeSkill",
                severity="critical",
            )
        ]
        fixed = fix_alignment_violations(tailored, violations)
        assert "FakeSkill" not in _values(fixed)
        # Only the fabrication goes; the user's real skills stay.
        assert _values(fixed) == _values(sample_resume)

    def test_removes_fabricated_cert(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        _values(tailored, "Certifications & Training").append("Fake Cert")
        violations = [
            AlignmentViolation(
                field_path="sections.values",
                violation_type="fabricated_cert",
                value="Fake Cert",
                severity="critical",
            )
        ]
        fixed = fix_alignment_violations(tailored, violations)
        assert "Fake Cert" not in _values(fixed, "Certifications & Training")

    def test_removes_fabricated_tag_from_a_tags_section(self, sample_resume):
        """A TAGS section's flat value list is cleaned by the same rule."""
        tailored = copy.deepcopy(sample_resume)
        tailored["sections"].append(
            {
                "id": "s-languages",
                "key": "spoken_languages",
                "heading": "Spoken Languages",
                "kind": "tags",
                "tags": ["English", "Klingon"],
            }
        )
        violations = [
            AlignmentViolation(
                field_path="sections.values",
                violation_type="fabricated_skill",
                value="Klingon",
                severity="critical",
            )
        ]
        fixed = fix_alignment_violations(tailored, violations)
        assert _section(fixed, "spoken_languages")["tags"] == ["English"]

    def test_removes_entry_with_fabricated_subtitle(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        _section(tailored, "experience")["entries"].append(
            {
                "id": "e-fake",
                "title": "Engineer",
                "subtitle": "FakeCompany Inc",
                "period": "2015 - 2017",
            }
        )
        violations = [
            AlignmentViolation(
                field_path="sections.experience.entries",
                violation_type="fabricated_company",
                value="FakeCompany Inc",
                severity="critical",
            )
        ]
        fixed = fix_alignment_violations(tailored, violations)
        subtitles = [
            entry["subtitle"] for entry in _section(fixed, "experience")["entries"]
        ]
        assert "FakeCompany Inc" not in subtitles
        assert subtitles == ["Acme Corp", "StartupCo"]

    def test_skips_non_critical_violations(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        original_skills = list(_values(tailored))
        violations = [
            AlignmentViolation(
                field_path="sections.values",
                violation_type="skill_variant",
                value="Python",
                severity="info",
            )
        ]
        fixed = fix_alignment_violations(tailored, violations)
        assert _values(fixed) == original_skills


class TestAnalyzeKeywordGaps:
    """Tests for analyze_keyword_gaps() — keyword matching analysis."""

    def test_finds_missing_keywords(self, sample_resume, master_resume, sample_job_keywords):
        analysis = analyze_keyword_gaps(sample_job_keywords, sample_resume, master_resume)
        # "Kubernetes" is in required_skills but not in the resume
        assert "Kubernetes" in analysis.missing_keywords

    def test_identifies_injectable_vs_non_injectable(self, sample_resume, master_resume, sample_job_keywords):
        analysis = analyze_keyword_gaps(sample_job_keywords, sample_resume, master_resume)
        # Every keyword lands in exactly one bucket
        all_jd = set(sample_job_keywords["required_skills"] + sample_job_keywords["preferred_skills"] + sample_job_keywords["keywords"])
        present = all_jd - set(analysis.missing_keywords)
        injectable = set(analysis.injectable_keywords)
        non_injectable = set(analysis.non_injectable_keywords)
        # Missing = injectable + non-injectable (no overlap)
        assert injectable | non_injectable == set(analysis.missing_keywords)
        assert injectable & non_injectable == set()
        # Present + missing = all keywords
        assert present | set(analysis.missing_keywords) == all_jd

    def test_keyword_only_in_master_is_injectable(self, sample_resume, master_resume):
        """The injectable bucket is what the writer is allowed to add."""
        master = copy.deepcopy(master_resume)
        _values(master).append("Terraform")
        keywords = {"required_skills": ["Terraform"], "preferred_skills": [], "keywords": []}
        analysis = analyze_keyword_gaps(keywords, sample_resume, master)
        assert analysis.injectable_keywords == ["Terraform"]
        assert analysis.non_injectable_keywords == []

    def test_calculates_match_percentage(self, sample_resume, master_resume, sample_job_keywords):
        analysis = analyze_keyword_gaps(sample_job_keywords, sample_resume, master_resume)
        assert 0.0 <= analysis.current_match_percentage <= 100.0
        assert analysis.potential_match_percentage >= analysis.current_match_percentage

    def test_keyword_already_present(self, sample_resume, master_resume):
        keywords = {"required_skills": ["Python"], "preferred_skills": [], "keywords": []}
        analysis = analyze_keyword_gaps(keywords, sample_resume, master_resume)
        assert "Python" not in analysis.missing_keywords
        assert analysis.current_match_percentage == 100.0


class TestCalculateKeywordMatch:
    """Tests for calculate_keyword_match() — percentage calculation."""

    def test_returns_percentage(self, sample_resume, sample_job_keywords):
        pct = calculate_keyword_match(sample_resume, sample_job_keywords)
        assert 0.0 <= pct <= 100.0

    def test_returns_zero_for_no_keywords(self, sample_resume):
        pct = calculate_keyword_match(sample_resume, {"required_skills": [], "preferred_skills": [], "keywords": []})
        assert pct == 0.0

    def test_returns_100_when_all_present(self, sample_resume):
        # Use keywords that are definitely in the resume
        keywords = {"required_skills": ["Python", "FastAPI"], "preferred_skills": [], "keywords": []}
        pct = calculate_keyword_match(sample_resume, keywords)
        assert pct == 100.0

    def test_matches_values_in_user_created_sections(self, sample_resume):
        """Keyword matching walks the whole document, not a fixed section list."""
        document = copy.deepcopy(sample_resume)
        document["sections"].append(
            {
                "id": "s-tools",
                "key": "tooling",
                "heading": "Tooling",
                "kind": "tags",
                "tags": ["Terraform"],
            }
        )
        keywords = {"required_skills": ["Terraform"], "preferred_skills": [], "keywords": []}
        assert calculate_keyword_match(document, keywords) == 100.0

    def test_word_boundary_matching(self, sample_resume):
        """'Go' should not match 'Google' or 'going'."""
        keywords = {"required_skills": ["Go"], "preferred_skills": [], "keywords": []}
        pct = calculate_keyword_match(sample_resume, keywords)
        # "Go" is not in the sample resume as a standalone word
        assert pct == 0.0


class TestRestoreBulletStyles:
    """H-04: a user's `plain` bullet must survive an AI rewrite.

    inject_keywords returns the model's JSON after only a structure check, and
    it is the LAST writer on the improve path. A model that rewrites a bullet
    routinely returns it with the default style, silently turning the user's
    plain paragraph row into a bulleted one. Prompt instructions are not a
    guarantee, so styles are restored locally from the source afterwards.
    """

    def test_restores_styles_the_llm_dropped(self):
        original = _document(
            bullets=[("Led migration", "plain"), ("Cut costs 40%", "bullet")]
        )
        improved = _document(
            bullets=[
                ("Led the platform migration", "bullet"),
                ("Reduced costs by 40%", "bullet"),
            ]
        )

        out = _restore_bullet_styles(original, improved)

        assert _styles(out) == ["plain", "bullet"]
        # The rewrite itself is kept; only the style comes from the source.
        assert [b["text"] for b in _bullets(out)] == [
            "Led the platform migration",
            "Reduced costs by 40%",
        ]

    def test_extra_row_from_the_model_keeps_the_default_style(self):
        original = _document(bullets=[("A", "plain")])
        improved = _document(bullets=[("A improved", "bullet"), ("B new", "bullet")])

        out = _restore_bullet_styles(original, improved)

        assert _styles(out) == ["plain", "bullet"]

    def test_model_supplied_style_never_overrides_the_source(self):
        """Style is the user's formatting choice, so the writer cannot flip it."""
        original = _document(bullets=[("A", "plain"), ("B", "plain")])
        improved = _document(bullets=[("A", "bullet"), ("B", "plain")])

        out = _restore_bullet_styles(original, improved)

        assert _styles(out) == ["plain", "plain"]

    def test_covers_user_created_sections(self):
        original = _document(
            bullets=[("Presented testing methods", "plain")],
            key="talks",
            heading="Talks",
        )
        improved = _document(
            bullets=[("Presented testing methodologies", "bullet")],
            key="talks",
            heading="Talks",
        )

        out = _restore_bullet_styles(original, improved)

        assert _styles(out, key="talks") == ["plain"]

    def test_matches_sections_by_key_not_position(self):
        """Section order is user-editable, so styles must pair by key."""
        original = _document(bullets=[("A", "plain")])
        original["sections"].append(
            {
                "id": "s-talks",
                "key": "talks",
                "heading": "Talks",
                "kind": "entries",
                "entries": [
                    {
                        "id": "e-talk",
                        "title": "Speaker",
                        "subtitle": "PyCon",
                        "bullets": [{"text": "B", "style": "bullet"}],
                    }
                ],
            }
        )
        improved = copy.deepcopy(original)
        improved["sections"].reverse()
        for section in improved["sections"]:
            for entry in section.get("entries", []):
                for bullet in entry["bullets"]:
                    bullet["text"] += " reworded"
                    bullet["style"] = "bullet"

        out = _restore_bullet_styles(original, improved)

        assert _styles(out, key="experience") == ["plain"]
        assert _styles(out, key="talks") == ["bullet"]
