"""Structured document diff.

Each case pins a distinction the old field-by-field engine could not make:
a rename is not a delete plus an add, a move is not a modification, and a
reword highlights only the words that changed.
"""

import copy
from typing import Any

import pytest

from app.schemas.document import migrate_document
from app.services.document_diff import (
    diff_documents,
    diff_tex_sources,
    merge_accepted,
    word_spans,
)

pytestmark = pytest.mark.unit


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


def _section(key: str, heading: str, kind: str, **content: Any) -> dict[str, Any]:
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


def _bullets(*texts: str) -> list[dict[str, str]]:
    return [{"text": text, "style": "bullet"} for text in texts]


def _document() -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "header": {"name": "Tom", "headline": "Engineer", "contacts": []},
        "sections": [
            _section("summary", "Summary", "text", text="Backend engineer."),
            _section(
                "experience",
                "Experience",
                "entries",
                entries=[
                    _entry(
                        "e1",
                        title="SWE",
                        subtitle="Acme",
                        bullets=_bullets("Built the scheduler", "Wrote tests"),
                    ),
                    _entry(
                        "e2",
                        title="Dev",
                        subtitle="Globex",
                        bullets=_bullets("Shipped things"),
                    ),
                    _entry(
                        "e3",
                        title="Intern",
                        subtitle="Initech",
                        bullets=_bullets("Learned a lot"),
                    ),
                ],
            ),
            _section(
                "skills",
                "Skills",
                "groups",
                groups=[{"label": "Languages", "values": ["Python", "Go"]}],
            ),
        ],
    }


def _diff(base: dict[str, Any], head: dict[str, Any], context: int = 0):
    return diff_documents(
        migrate_document(base), migrate_document(head), context=context
    )


def _rows(diff, status: str) -> list[Any]:
    return [row for section in diff.sections for row in section.rows if row.status == status]


def test_a_renamed_heading_is_a_rename_not_a_remove_and_add() -> None:
    base = _document()
    head = copy.deepcopy(base)
    head["sections"][0]["heading"] = "About Me"

    diff = _diff(base, head)

    renamed = [s for s in diff.sections if s.status == "renamed"]
    assert len(renamed) == 1
    assert (renamed[0].base_heading, renamed[0].head_heading) == ("Summary", "About Me")
    assert diff.stats.sections_added == 0
    assert diff.stats.sections_removed == 0


def test_a_reordered_entry_is_a_move_not_a_modification() -> None:
    base = _document()
    head = copy.deepcopy(base)
    entries = head["sections"][1]["entries"]
    entries.insert(0, entries.pop(2))

    diff = _diff(base, head)

    moved = _rows(diff, "moved")
    assert [row.head_text for row in moved] == ["Intern | Initech"]
    assert diff.stats.entries_moved == 1
    assert diff.stats.entries_modified == 0
    # The other two entries kept their relative order, so they did not move.
    assert diff.stats.entries_added == 0
    assert diff.stats.entries_removed == 0


def test_word_spans_cover_only_the_changed_words() -> None:
    base = _document()
    head = copy.deepcopy(base)
    head["sections"][1]["entries"][0]["bullets"][0]["text"] = (
        "Built the distributed scheduler"
    )

    diff = _diff(base, head)
    modified = _rows(diff, "modified")

    assert len(modified) == 1
    row = modified[0]
    assert row.path == "sections.experience.entries[0].bullets[0].text"
    highlighted = [row.head_text[span.start : span.end] for span in row.spans]
    assert highlighted == ["distributed "]


def test_the_three_change_scenario_counts_exactly_three() -> None:
    """Rename + reorder + reword: the summary bar must not inflate."""
    base = _document()
    head = copy.deepcopy(base)
    head["sections"][0]["heading"] = "About Me"
    entries = head["sections"][1]["entries"]
    entries.insert(0, entries.pop(2))
    entries[1]["bullets"][0]["text"] = "Built the distributed scheduler"

    diff = _diff(base, head)

    assert diff.stats.sections_renamed == 1
    assert diff.stats.entries_moved == 1
    assert diff.stats.bullets_modified == 1
    assert diff.stats.total_changes == 3


def test_whitespace_only_edits_produce_no_spans() -> None:
    assert word_spans("one  two", "one two") == []


def test_context_zero_drops_unchanged_rows() -> None:
    base = _document()
    head = copy.deepcopy(base)
    head["sections"][1]["entries"][0]["bullets"][0]["text"] = "Built the new scheduler"

    trimmed = _diff(base, head, context=0)
    padded = _diff(base, head, context=2)

    assert all(
        row.status != "unchanged" for section in trimmed.sections for row in section.rows
    )
    assert any(
        row.status == "unchanged" for section in padded.sections for row in section.rows
    )


def test_added_and_removed_sections_are_reported_once_each() -> None:
    base = _document()
    head = copy.deepcopy(base)
    head["sections"].pop(2)
    head["sections"].append(
        _section("military_service", "Military Service", "entries",
                 entries=[_entry("m1", title="Officer", subtitle="Unit 8200")])
    )

    diff = _diff(base, head)

    assert diff.stats.sections_removed == 1
    assert diff.stats.sections_added == 1
    statuses = {s.head_key or s.base_key: s.status for s in diff.sections}
    assert statuses["skills"] == "removed"
    assert statuses["military_service"] == "added"


def test_group_values_pair_by_label_not_position() -> None:
    base = _document()
    head = copy.deepcopy(base)
    head["sections"][2]["groups"] = [
        {"label": "Cloud", "values": ["AWS"]},
        {"label": "Languages", "values": ["Python", "Go", "Rust"]},
    ]

    diff = _diff(base, head)
    added = [row.head_text for row in _rows(diff, "added")]

    # Rust is the only new *value*; Python and Go must not read as re-added
    # merely because their group moved.
    assert "Rust" in added
    assert "Python" not in added


def test_header_changes_are_reported_outside_the_sections() -> None:
    base = _document()
    head = copy.deepcopy(base)
    head["header"]["name"] = "Tom Bar"

    diff = _diff(base, head)

    changed = [row for row in diff.header if row.status != "unchanged"]
    assert [(row.path, row.base_text, row.head_text) for row in changed] == [
        ("header.name", "Tom", "Tom Bar")
    ]


def test_tex_diff_reports_changed_lines() -> None:
    rows = diff_tex_sources(
        "\\documentclass{article}\n\\titlespacing{1pt}\n\\begin{document}",
        "\\documentclass{article}\n\\titlespacing{0pt}\n\\begin{document}",
        context=0,
    )

    assert [row.status for row in rows] == ["modified"]
    assert rows[0].head_text == "\\titlespacing{0pt}"


class TestMergeAccepted:
    """Partial accept: only the ticked rows land."""

    def _proposal(self) -> tuple[dict[str, Any], dict[str, Any]]:
        base = _document()
        head = copy.deepcopy(base)
        head["sections"][0]["text"] = "Senior backend engineer."
        head["sections"][1]["entries"][0]["bullets"][0]["text"] = "Built the K8s scheduler"
        head["sections"][1]["entries"][0]["bullets"][1]["text"] = "Wrote many tests"
        head["sections"][1]["entries"][1]["bullets"][0]["text"] = "Shipped many things"
        return base, head

    def test_only_the_named_paths_are_taken(self) -> None:
        base, head = self._proposal()

        merged = merge_accepted(
            migrate_document(base),
            migrate_document(head),
            {
                "sections.summary.text",
                "sections.experience.entries[0].bullets[0].text",
            },
        )

        assert merged.section("summary").text == "Senior backend engineer."
        experience = merged.section("experience")
        assert [b.text for b in experience.entries[0].bullets] == [
            "Built the K8s scheduler",
            "Wrote tests",
        ]
        assert [b.text for b in experience.entries[1].bullets] == ["Shipped things"]

    def test_accepting_nothing_returns_the_original(self) -> None:
        base, head = self._proposal()

        merged = merge_accepted(migrate_document(base), migrate_document(head), set())

        assert merged.model_dump(mode="json") == migrate_document(base).model_dump(
            mode="json"
        )

    def test_accepting_everything_matches_the_proposal(self) -> None:
        base, head = self._proposal()
        diff = _diff(base, head)
        paths = {
            row.path
            for section in diff.sections
            for row in section.rows
            if row.status == "modified"
        }

        merged = merge_accepted(migrate_document(base), migrate_document(head), paths)

        assert merged.model_dump(mode="json") == migrate_document(head).model_dump(
            mode="json"
        )

    def test_an_accepted_appended_bullet_is_added(self) -> None:
        base = _document()
        head = copy.deepcopy(base)
        head["sections"][1]["entries"][0]["bullets"].append(
            {"text": "Cut deploy time 40%", "style": "bullet"}
        )

        merged = merge_accepted(
            migrate_document(base),
            migrate_document(head),
            {"sections.experience.entries[0].bullets[2].text"},
        )

        assert [b.text for b in merged.section("experience").entries[0].bullets] == [
            "Built the scheduler",
            "Wrote tests",
            "Cut deploy time 40%",
        ]
