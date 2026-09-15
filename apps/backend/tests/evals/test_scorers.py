"""Deterministic tests for the structural scorers.

This is the anti-theater proof for the eval harness: every scorer is exercised
with BOTH a known-good and a known-bad input, so we know it actually detects
violations instead of always returning "OK". None of these tests touch an LLM
or the network — they run for free in the normal suite.

The ``tailored_good`` / ``tailored_bad`` golden fixtures double as realistic
end-to-end checks: the good tailoring must pass every scorer, the bad one must
trip the relevant scorers.
"""

from typing import Any

import copy

import pytest

from tests.evals.golden.cases import GOLDEN_CASES
from tests.evals.scorers import (
    flatten_resume_text,
    header_unchanged,
    is_valid_resume,
    jd_keywords_present,
    no_fabricated_entries,
    sections_preserved,
)


def _section(document: dict[str, Any], key: str) -> dict[str, Any]:
    """The section of ``document`` with ``key`` (raises if the test mistyped it)."""
    return next(section for section in document["sections"] if section["key"] == key)


def _drop_section(document: dict[str, Any], key: str) -> None:
    document["sections"] = [
        section for section in document["sections"] if section["key"] != key
    ]


def _summary_document(text: str) -> dict[str, Any]:
    """Minimal single-TEXT-section document, for keyword-matching cases."""
    return {
        "schemaVersion": 2,
        "sections": [
            {"key": "summary", "heading": "Summary", "kind": "text", "text": text}
        ],
    }


class TestSectionsPreserved:
    def test_identical_resume_preserves_all_sections(self, sample_resume):
        assert sections_preserved(sample_resume, sample_resume) is True

    def test_emptying_an_entries_section_fails(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        _section(tailored, "experience")["entries"] = []
        assert sections_preserved(sample_resume, tailored) is False

    def test_deleting_a_section_outright_fails(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        _drop_section(tailored, "education")
        assert sections_preserved(sample_resume, tailored) is False

    def test_emptying_a_text_section_fails(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        _section(tailored, "summary")["text"] = "   "
        assert sections_preserved(sample_resume, tailored) is False

    def test_emptying_group_values_fails(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        for group in _section(tailored, "skills")["groups"]:
            group["values"] = []
        assert sections_preserved(sample_resume, tailored) is False

    def test_originally_empty_section_is_not_required(self, sample_resume):
        original = copy.deepcopy(sample_resume)
        _section(original, "projects")["entries"] = []
        tailored = copy.deepcopy(original)
        # projects was empty to begin with, so staying empty is fine.
        assert sections_preserved(original, tailored) is True

    def test_a_section_renamed_by_the_ai_does_not_count_as_survival(
        self, sample_resume
    ):
        # Sections are matched by key, the stable change-path identifier: a
        # heading rewrite is allowed, a key rewrite loses the section.
        renamed = copy.deepcopy(sample_resume)
        _section(renamed, "experience")["key"] = "work_history"
        assert sections_preserved(sample_resume, renamed) is False

        reheaded = copy.deepcopy(sample_resume)
        _section(reheaded, "experience")["heading"] = "Where I Worked"
        assert sections_preserved(sample_resume, reheaded) is True

    def test_rewording_bullets_still_preserves_sections(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        _section(tailored, "experience")["entries"][0]["bullets"] = [
            {"text": "Completely reworded bullet", "style": "bullet"}
        ]
        assert sections_preserved(sample_resume, tailored) is True


class TestNoFabricatedEntries:
    def test_same_entries_returns_empty_list(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        assert no_fabricated_entries(sample_resume, tailored) == []

    def test_reworded_bullets_same_entries_is_truthful(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        for entry in _section(tailored, "experience")["entries"]:
            entry["bullets"] = [{"text": "reworded for the JD", "style": "bullet"}]
        assert no_fabricated_entries(sample_resume, tailored) == []

    def test_invented_employer_is_detected(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        _section(tailored, "experience")["entries"].append(
            {
                "id": "e-globex",
                "title": "Principal Engineer",
                "subtitle": "Globex Industries",
                "period": "2015 - Present",
                "bullets": [{"text": "never happened", "style": "bullet"}],
            }
        )
        assert no_fabricated_entries(sample_resume, tailored) == [
            "Principal Engineer — Globex Industries"
        ]

    def test_invented_entry_in_a_custom_section_is_detected(self, sample_resume):
        # Fabrication detection is not limited to the built-in experience
        # section: a user-authored section is checked the same way.
        original = copy.deepcopy(sample_resume)
        original["sections"].append(
            {
                "id": "s-volunteering",
                "key": "volunteering",
                "heading": "Volunteering",
                "kind": "entries",
                "entries": [
                    {"id": "v-1", "title": "Mentor", "subtitle": "Code Club"}
                ],
            }
        )
        tailored = copy.deepcopy(original)
        _section(tailored, "volunteering")["entries"].append(
            {"id": "v-2", "title": "Trustee", "subtitle": "Invented Foundation"}
        )
        assert no_fabricated_entries(original, tailored) == [
            "Trustee — Invented Foundation"
        ]

    def test_case_and_whitespace_insensitive(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        entry = _section(tailored, "experience")["entries"][0]
        entry["title"] = "  senior backend   engineer "
        entry["subtitle"] = "  acme corp  "
        # Same entry, different casing/whitespace — not a fabrication.
        assert no_fabricated_entries(sample_resume, tailored) == []

    def test_each_fabricated_entry_listed_once(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        _section(tailored, "experience")["entries"] = [
            {"id": "x1", "title": "Principal Engineer", "subtitle": "Globex Industries"},
            {"id": "x2", "title": "Principal Engineer", "subtitle": "Globex Industries"},
        ]
        assert no_fabricated_entries(sample_resume, tailored) == [
            "Principal Engineer — Globex Industries"
        ]


class TestJdKeywordsPresent:
    def test_all_keywords_present_scores_one(self, sample_resume):
        keywords = ["Python", "FastAPI", "Docker", "AWS"]
        assert jd_keywords_present(sample_resume, keywords) == 1.0

    def test_no_keywords_present_scores_zero(self, sample_resume):
        keywords = ["Rust", "Kubernetes", "Elixir", "COBOL"]
        assert jd_keywords_present(sample_resume, keywords) == 0.0

    def test_partial_match_is_fractional(self, sample_resume):
        # 2 of 4 present.
        keywords = ["Python", "FastAPI", "Rust", "Elixir"]
        assert jd_keywords_present(sample_resume, keywords) == pytest.approx(0.5)

    def test_match_is_case_insensitive(self, sample_resume):
        assert jd_keywords_present(sample_resume, ["python", "fastapi"]) == 1.0

    def test_empty_keyword_list_scores_one(self, sample_resume):
        assert jd_keywords_present(sample_resume, []) == 1.0

    def test_latin_keywords_adjacent_to_cjk_keep_term_boundaries(self) -> None:
        mixed_script = _summary_document("Pythonによる開発、熟悉Java开发")
        javascript_only = _summary_document("负责JavaScript平台开发")

        assert jd_keywords_present(mixed_script, ["Python", "Java"]) == 1.0
        assert jd_keywords_present(javascript_only, ["Java", "JavaScript"]) == 0.5

    def test_searches_every_section_kind(self, sample_resume):
        # "microservices" only appears inside an experience bullet, "Redis"
        # only inside a skills group, "honors" only in an entry summary.
        assert jd_keywords_present(
            sample_resume, ["microservices", "Redis", "honors"]
        ) == 1.0

    @pytest.mark.parametrize(
        "surrounding", [("𠀀", "𰀀"), ("개발", "개발"), ("ᄀ", "ᄂ")]
    )
    def test_extended_cjk_boundaries_preserve_latin_terms(
        self, surrounding: tuple[str, str]
    ) -> None:
        before, after = surrounding
        assert jd_keywords_present(_summary_document(f"{before}Java{after}"), ["Java"]) == 1.0
        assert (
            jd_keywords_present(_summary_document(f"{before}JavaScript{after}"), ["Java"])
            == 0.0
        )


class TestIsValidResume:
    def test_well_formed_resume_is_valid(self, sample_resume):
        assert is_valid_resume(sample_resume) is True

    def test_empty_dict_is_not_meaningful_despite_schema_defaults(self) -> None:
        assert is_valid_resume({}) is False

    def test_wrong_type_for_sections_is_invalid(self, sample_resume):
        broken = copy.deepcopy(sample_resume)
        broken["sections"] = "not a list"
        assert is_valid_resume(broken) is False

    def test_wrong_type_for_header_is_invalid(self, sample_resume):
        broken = copy.deepcopy(sample_resume)
        broken["header"] = "nope"
        assert is_valid_resume(broken) is False

    def test_unknown_section_kind_is_invalid(self, sample_resume):
        broken = copy.deepcopy(sample_resume)
        _section(broken, "summary")["kind"] = "freeform"
        assert is_valid_resume(broken) is False


class TestHeaderUnchanged:
    def test_identical_header_is_unchanged(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        assert header_unchanged(sample_resume, tailored) is True

    def test_changed_name_is_flagged(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        tailored["header"]["name"] = "Someone Else"
        assert header_unchanged(sample_resume, tailored) is False

    def test_changed_contact_value_is_flagged(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        tailored["header"]["contacts"][0]["value"] = "attacker@example.com"
        assert header_unchanged(sample_resume, tailored) is False

    def test_dropped_contact_is_flagged(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        del tailored["header"]["contacts"][-1]
        assert header_unchanged(sample_resume, tailored) is False

    def test_editing_other_sections_does_not_trip_it(self, sample_resume):
        tailored = copy.deepcopy(sample_resume)
        _section(tailored, "summary")["text"] = "totally different summary"
        assert header_unchanged(sample_resume, tailored) is True


class TestFlattenResumeText:
    def test_includes_header_and_nested_bullet_text(self, sample_resume):
        text = flatten_resume_text(sample_resume)
        assert "rest apis" in text
        assert "jane doe" in text

    def test_output_is_lowercased(self, sample_resume):
        text = flatten_resume_text(sample_resume)
        assert text == text.lower()


class TestGoldenCasesStructural:
    """The golden good/bad tailorings must score exactly as designed."""

    @pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c["name"])
    def test_good_tailoring_passes_every_scorer(self, case: dict[str, Any]) -> None:
        original = case["original"]
        good = case["tailored_good"]
        assert is_valid_resume(original) is True
        assert is_valid_resume(good) is True
        assert sections_preserved(original, good) is True
        assert no_fabricated_entries(original, good) == []
        assert header_unchanged(original, good) is True
        assert jd_keywords_present(good, case["grounded_keywords"]) == 1.0

    @pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c["name"])
    def test_bad_tailoring_is_caught(self, case):
        original = case["original"]
        bad = case["tailored_bad"]
        # The bad fixture violates at least one truthfulness/preservation rule:
        # it drops a section, invents an employer, OR rewrites the identity.
        violated = (
            not sections_preserved(original, bad)
            or bool(no_fabricated_entries(original, bad))
            or not header_unchanged(original, bad)
        )
        assert violated is True
        # Specifically, every bad fixture fabricates an employer and changes
        # the candidate's name.
        assert no_fabricated_entries(original, bad) != []
        assert header_unchanged(original, bad) is False
