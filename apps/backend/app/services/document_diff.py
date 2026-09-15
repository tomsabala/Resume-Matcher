"""Structured diff over the dynamic resume document.

One engine backs every comparison surface: resume-vs-resume,
version-vs-version and resume-vs-AI-suggestion. It produces a *tree* diff —
sections pair by identity, entries pair inside their section, and only the
leaves are compared as text — so renaming a heading reads as a rename, and
moving an entry reads as a move, rather than as a delete plus an add.

Every pairing rule is pinned here rather than made configurable: a diff whose
thresholds vary per deployment is a diff nobody can reason about.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Literal

from app.schemas.diff import (
    DiffAnchor,
    DiffRow,
    DiffSpan,
    DiffStats,
    DocumentDiff,
    RowKind,
    RowStatus,
    SectionDiff,
    SectionStatus,
)
from app.schemas.document import Entry, ResumeDocument, Section, SectionKind

__all__ = [
    "DiffAnchor",
    "DiffRow",
    "DiffSpan",
    "DiffStats",
    "DocumentDiff",
    "SectionDiff",
    "diff_documents",
    "diff_tex_sources",
]

# Unmatched sections pair when their headings are this similar. Entries use the
# same bar on "title subtitle".
_HEADING_SIMILARITY = 0.80
# Inside a `replace` opcode, two rows pair as a modification rather than an
# unrelated delete+insert at this similarity.
_ROW_SIMILARITY = 0.60

# Tokens keep their trailing whitespace so character offsets stay exact.
_TOKEN_RE = re.compile(r"\S+|\s+")


def _ratio(left: str, right: str) -> float:
    return SequenceMatcher(None, left.strip().casefold(), right.strip().casefold()).ratio()


def word_spans(base: str, head: str) -> list[DiffSpan]:
    """Character ranges of the words that differ between two strings.

    Whitespace-only differences produce no span: re-wrapping a bullet is not a
    change the reader needs highlighted.
    """
    base_tokens = _TOKEN_RE.findall(base)
    head_tokens = _TOKEN_RE.findall(head)
    base_offsets: list[int] = []
    offset = 0
    for token in base_tokens:
        base_offsets.append(offset)
        offset += len(token)
    head_offsets: list[int] = []
    offset = 0
    for token in head_tokens:
        head_offsets.append(offset)
        offset += len(token)

    def span(
        side: Literal["base", "head"],
        tokens: list[str],
        offsets: list[int],
        start: int,
        end: int,
        op: Literal["insert", "delete", "replace"],
    ) -> DiffSpan | None:
        if start >= end:
            return None
        text = "".join(tokens[start:end])
        if not text.strip():
            return None
        return DiffSpan(
            side=side,
            start=offsets[start],
            end=offsets[start] + len(text),
            op=op,
        )

    spans: list[DiffSpan] = []
    matcher = SequenceMatcher(None, base_tokens, head_tokens, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("delete", "replace"):
            found = span("base", base_tokens, base_offsets, i1, i2, tag)  # type: ignore[arg-type]
            if found is not None:
                spans.append(found)
        if tag in ("insert", "replace"):
            found = span("head", head_tokens, head_offsets, j1, j2, tag)  # type: ignore[arg-type]
            if found is not None:
                spans.append(found)
    return spans


def _text_row(
    kind: RowKind,
    path: str,
    base: str | None,
    head: str | None,
    anchor: DiffAnchor,
    *,
    moved: bool = False,
) -> DiffRow:
    """Compare two optional strings into one row."""
    if base is None:
        status: RowStatus = "added"
    elif head is None:
        status = "removed"
    elif base.strip() == head.strip():
        status = "moved" if moved else "unchanged"
    else:
        status = "modified"
    row = DiffRow(
        kind=kind, status=status, path=path, base_text=base, head_text=head, anchor=anchor
    )
    if status == "modified":
        row.spans = word_spans(base or "", head or "")
    return row


def _pair_by_identity(
    base_items: list[tuple[str, str]], head_items: list[tuple[str, str]]
) -> dict[int, int]:
    """Pair items by exact id, then exact key/identity, then similarity.

    Returns ``{base_index: head_index}``. Falling back through three rules is
    what lets a rename stay a rename: the id survives it, and when it does not,
    the text still matches closely enough to pair.
    """
    pairs: dict[int, int] = {}
    taken: set[int] = set()

    for rule in (0, 1):
        for base_index, base_item in enumerate(base_items):
            if base_index in pairs or not base_item[rule]:
                continue
            for head_index, head_item in enumerate(head_items):
                if head_index in taken:
                    continue
                if base_item[rule] and base_item[rule] == head_item[rule]:
                    pairs[base_index] = head_index
                    taken.add(head_index)
                    break

    for base_index, base_item in enumerate(base_items):
        if base_index in pairs:
            continue
        best_index: int | None = None
        best_score = _HEADING_SIMILARITY
        for head_index, head_item in enumerate(head_items):
            if head_index in taken:
                continue
            score = _ratio(base_item[1], head_item[1])
            if score >= best_score:
                best_score = score
                best_index = head_index
        if best_index is not None:
            pairs[base_index] = best_index
            taken.add(best_index)
    return pairs


def _pair_strings(base: list[str], head: list[str]) -> list[tuple[int | None, int | None]]:
    """Pair two string lists positionally via ``SequenceMatcher`` opcodes.

    Within a ``replace`` run, rows that are similar enough pair up as
    modifications; the rest fall out as separate removals and additions.
    """
    pairs: list[tuple[int | None, int | None]] = []
    matcher = SequenceMatcher(None, base, head, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs.extend((i, j) for i, j in zip(range(i1, i2), range(j1, j2)))
        elif tag == "delete":
            pairs.extend((i, None) for i in range(i1, i2))
        elif tag == "insert":
            pairs.extend((None, j) for j in range(j1, j2))
        else:
            base_run = list(range(i1, i2))
            head_run = list(range(j1, j2))
            used: set[int] = set()
            for i in base_run:
                match: int | None = None
                best = _ROW_SIMILARITY
                for j in head_run:
                    if j in used:
                        continue
                    score = _ratio(base[i], head[j])
                    if score >= best:
                        best = score
                        match = j
                if match is None:
                    pairs.append((i, None))
                else:
                    used.add(match)
                    pairs.append((i, match))
            pairs.extend((None, j) for j in head_run if j not in used)
    return pairs


def _moved_base_indices(pairs: dict[int, int]) -> set[int]:
    """Which paired items actually moved, relative to the others.

    Comparing indices directly would call *both* items moved when two swap,
    and would mark everything after an insertion as moved. Instead, the
    longest run that stayed in relative order is treated as stationary and
    only the rest count — which is what a reader means by "this one moved".
    """
    ordered = sorted(pairs.items())
    if len(ordered) < 2:
        return set()

    # Longest increasing subsequence over the head positions, O(n^2) — a
    # resume has tens of sections, not thousands.
    best_length = [1] * len(ordered)
    previous = [-1] * len(ordered)
    for index in range(len(ordered)):
        for earlier in range(index):
            if (
                ordered[earlier][1] < ordered[index][1]
                and best_length[earlier] + 1 > best_length[index]
            ):
                best_length[index] = best_length[earlier] + 1
                previous[index] = earlier

    cursor = max(range(len(ordered)), key=lambda index: best_length[index])
    stationary: set[int] = set()
    while cursor != -1:
        stationary.add(ordered[cursor][0])
        cursor = previous[cursor]
    return {base_index for base_index, _ in ordered} - stationary


def _entry_rows(
    section_key: str,
    section_id: str,
    base_entries: list[Entry],
    head_entries: list[Entry],
    stats: DiffStats,
) -> list[DiffRow]:
    """Rows for one ``ENTRIES`` section: an entry header row plus its leaves."""
    pairs = _pair_by_identity(
        [(entry.id, f"{entry.title} {entry.subtitle}") for entry in base_entries],
        [(entry.id, f"{entry.title} {entry.subtitle}") for entry in head_entries],
    )
    matched_heads = set(pairs.values())
    moved_indices = _moved_base_indices(pairs)
    rows: list[DiffRow] = []

    for base_index, base_entry in enumerate(base_entries):
        head_index = pairs.get(base_index)
        if head_index is None:
            stats.entries_removed += 1
            rows.append(
                DiffRow(
                    kind="entry",
                    status="removed",
                    path=f"sections.{section_key}.entries[{base_index}]",
                    base_text=_entry_label(base_entry),
                    anchor=DiffAnchor(
                        section_id=section_id,
                        section_key=section_key,
                        entry_id=base_entry.id,
                        index=base_index,
                    ),
                )
            )
            continue

        head_entry = head_entries[head_index]
        anchor = DiffAnchor(
            section_id=section_id,
            section_key=section_key,
            entry_id=head_entry.id,
            index=head_index,
        )
        moved = base_index in moved_indices
        header = _text_row(
            "entry",
            f"sections.{section_key}.entries[{head_index}]",
            _entry_label(base_entry),
            _entry_label(head_entry),
            anchor,
            moved=moved,
        )
        rows.append(header)
        if header.status == "moved":
            stats.entries_moved += 1
        elif header.status == "modified":
            stats.entries_modified += 1

        if base_entry.summary or head_entry.summary:
            summary = _text_row(
                "text",
                f"sections.{section_key}.entries[{head_index}].summary",
                base_entry.summary,
                head_entry.summary,
                anchor,
            )
            rows.append(summary)
            if summary.status == "modified":
                stats.bullets_modified += 1

        base_bullets = [bullet.text for bullet in base_entry.bullets]
        head_bullets = [bullet.text for bullet in head_entry.bullets]
        for base_row, head_row in _pair_strings(base_bullets, head_bullets):
            path_index = head_row if head_row is not None else base_row
            row = _text_row(
                "bullet",
                f"sections.{section_key}.entries[{head_index}].bullets[{path_index}].text",
                base_bullets[base_row] if base_row is not None else None,
                head_bullets[head_row] if head_row is not None else None,
                anchor,
            )
            rows.append(row)
            if row.status == "added":
                stats.bullets_added += 1
            elif row.status == "removed":
                stats.bullets_removed += 1
            elif row.status == "modified":
                stats.bullets_modified += 1

    for head_index, head_entry in enumerate(head_entries):
        if head_index in matched_heads:
            continue
        stats.entries_added += 1
        rows.append(
            DiffRow(
                kind="entry",
                status="added",
                path=f"sections.{section_key}.entries[{head_index}]",
                head_text=_entry_label(head_entry),
                anchor=DiffAnchor(
                    section_id=head_entry.id and section_id,
                    section_key=section_key,
                    entry_id=head_entry.id,
                    index=head_index,
                ),
            )
        )
    return rows


def _entry_label(entry: Entry) -> str:
    parts = [entry.title, entry.subtitle, entry.period]
    return " | ".join(part for part in parts if part)


def _value_rows(
    kind: RowKind,
    path: str,
    section_id: str,
    section_key: str,
    base_values: list[str],
    head_values: list[str],
    stats: DiffStats,
) -> list[DiffRow]:
    """Rows for a flat list of short values."""
    rows: list[DiffRow] = []
    anchor = DiffAnchor(section_id=section_id, section_key=section_key)
    for base_index, head_index in _pair_strings(base_values, head_values):
        row = _text_row(
            kind,
            path,
            base_values[base_index] if base_index is not None else None,
            head_values[head_index] if head_index is not None else None,
            anchor,
        )
        rows.append(row)
        if row.status == "added":
            stats.tags_added += 1
        elif row.status == "removed":
            stats.tags_removed += 1
    return rows


def _section_rows(base: Section, head: Section, stats: DiffStats) -> list[DiffRow]:
    """Content rows for a matched pair of sections."""
    if head.kind is not base.kind:
        # A kind change replaces the content wholesale; render it as such
        # rather than pretending the shapes are comparable.
        return [
            *_section_content_rows(base, base, stats, side="base"),
            *_section_content_rows(head, head, stats, side="head"),
        ]

    key = head.key
    if base.kind is SectionKind.TEXT:
        row = _text_row(
            "text",
            f"sections.{key}.text",
            base.text,
            head.text,
            DiffAnchor(section_id=head.id, section_key=key),
        )
        if row.status == "modified":
            stats.bullets_modified += 1
        return [row]

    if base.kind is SectionKind.ENTRIES:
        return _entry_rows(key, head.id, base.entries, head.entries, stats)

    if base.kind is SectionKind.TAGS:
        return _value_rows(
            "tag", f"sections.{key}.tags", head.id, key, base.tags, head.tags, stats
        )

    rows: list[DiffRow] = []
    group_pairs = _pair_by_identity(
        [(group.label, group.label) for group in base.groups],
        [(group.label, group.label) for group in head.groups],
    )
    matched = set(group_pairs.values())
    for base_index, base_group in enumerate(base.groups):
        head_index = group_pairs.get(base_index)
        if head_index is None:
            rows.extend(
                _value_rows(
                    "group",
                    f"sections.{key}.groups[{base_index}].values",
                    head.id,
                    key,
                    base_group.values,
                    [],
                    stats,
                )
            )
            continue
        head_group = head.groups[head_index]
        rows.append(
            _text_row(
                "group",
                f"sections.{key}.groups[{head_index}].label",
                base_group.label,
                head_group.label,
                DiffAnchor(section_id=head.id, section_key=key, index=head_index),
            )
        )
        rows.extend(
            _value_rows(
                "group",
                f"sections.{key}.groups[{head_index}].values",
                head.id,
                key,
                base_group.values,
                head_group.values,
                stats,
            )
        )
    for head_index, head_group in enumerate(head.groups):
        if head_index in matched:
            continue
        rows.extend(
            _value_rows(
                "group",
                f"sections.{key}.groups[{head_index}].values",
                head.id,
                key,
                [],
                head_group.values,
                stats,
            )
        )
    return rows


def _section_content_rows(
    section: Section, other: Section, stats: DiffStats, *, side: Literal["base", "head"]
) -> list[DiffRow]:
    """Every row of a section, all on one side (added or removed wholesale)."""
    empty = section.model_copy(deep=True)
    empty.text = ""
    empty.entries = []
    empty.tags = []
    empty.groups = []
    if side == "base":
        return _section_rows(section, empty, stats)
    return _section_rows(empty, section, stats)


def _header_rows(base: ResumeDocument, head: ResumeDocument) -> list[DiffRow]:
    """Name, headline and each contact."""
    rows = [
        _text_row("text", "header.name", base.header.name, head.header.name, DiffAnchor()),
        _text_row(
            "text",
            "header.headline",
            base.header.headline,
            head.header.headline,
            DiffAnchor(),
        ),
    ]
    base_contacts = {contact.kind: contact for contact in base.header.contacts}
    head_contacts = {contact.kind: contact for contact in head.header.contacts}
    for kind in sorted(base_contacts.keys() | head_contacts.keys()):
        base_contact = base_contacts.get(kind)
        head_contact = head_contacts.get(kind)
        rows.append(
            _text_row(
                "text",
                f"header.contacts[{kind}]",
                base_contact.value if base_contact else None,
                head_contact.value if head_contact else None,
                DiffAnchor(),
            )
        )
    return rows


def _trim_context(rows: list[DiffRow], context: int) -> list[DiffRow]:
    """Keep only ``context`` unchanged rows around each change."""
    if context < 0:
        return rows
    keep = [row.status != "unchanged" for row in rows]
    for index, changed in enumerate(list(keep)):
        if not changed:
            continue
        for offset in range(1, context + 1):
            if index - offset >= 0:
                keep[index - offset] = True
            if index + offset < len(rows):
                keep[index + offset] = True
    return [row for row, kept in zip(rows, keep) if kept]


def diff_documents(
    base: ResumeDocument, head: ResumeDocument, *, context: int = 2
) -> DocumentDiff:
    """Compare two documents into a section-grouped, GitHub-style diff.

    ``context`` trims runs of unchanged rows; ``0`` returns changes only.
    """
    stats = DiffStats()
    base_sections = base.sections
    head_sections = head.sections
    pairs = _pair_by_identity(
        [(section.id, section.heading) for section in base_sections],
        [(section.id, section.heading) for section in head_sections],
    )
    # A section whose id changed can still pair on its key, which is stable
    # across a re-import.
    for base_index, base_section in enumerate(base_sections):
        if base_index in pairs:
            continue
        for head_index, head_section in enumerate(head_sections):
            if head_index in pairs.values():
                continue
            if base_section.key == head_section.key:
                pairs[base_index] = head_index
                break

    matched_heads = set(pairs.values())
    moved_sections = _moved_base_indices(pairs)
    section_diffs: list[SectionDiff] = []

    for base_index, base_section in enumerate(base_sections):
        head_index = pairs.get(base_index)
        if head_index is None:
            stats.sections_removed += 1
            section_diffs.append(
                SectionDiff(
                    status="removed",
                    base_key=base_section.key,
                    base_heading=base_section.heading,
                    base_index=base_index,
                    rows=_trim_context(
                        _section_content_rows(base_section, base_section, stats, side="base"),
                        context,
                    ),
                )
            )
            continue

        head_section = head_sections[head_index]
        rows = _section_rows(base_section, head_section, stats)
        renamed = base_section.heading.strip() != head_section.heading.strip()
        moved = base_index in moved_sections
        changed = any(row.status != "unchanged" for row in rows)

        if renamed:
            status: SectionStatus = "renamed"
            stats.sections_renamed += 1
        elif changed:
            status = "modified"
        elif moved:
            status = "moved"
        else:
            status = "unchanged"
        # A move is counted once even when the section also changed, so the
        # summary never double-counts one section.
        if moved:
            stats.sections_moved += 1

        section_diffs.append(
            SectionDiff(
                status=status,
                base_key=base_section.key,
                head_key=head_section.key,
                base_heading=base_section.heading,
                head_heading=head_section.heading,
                base_index=base_index,
                head_index=head_index,
                rows=_trim_context(rows, context),
            )
        )

    for head_index, head_section in enumerate(head_sections):
        if head_index in matched_heads:
            continue
        stats.sections_added += 1
        section_diffs.append(
            SectionDiff(
                status="added",
                head_key=head_section.key,
                head_heading=head_section.heading,
                head_index=head_index,
                rows=_trim_context(
                    _section_content_rows(head_section, head_section, stats, side="head"),
                    context,
                ),
            )
        )

    section_diffs.sort(
        key=lambda diff: (
            diff.head_index if diff.head_index is not None else diff.base_index or 0
        )
    )
    header = _trim_context(_header_rows(base, head), context)

    stats.total_changes = (
        stats.sections_added
        + stats.sections_removed
        + stats.sections_renamed
        + stats.sections_moved
        + stats.entries_added
        + stats.entries_removed
        + stats.entries_modified
        + stats.entries_moved
        + stats.bullets_added
        + stats.bullets_removed
        + stats.bullets_modified
        + stats.tags_added
        + stats.tags_removed
    )
    return DocumentDiff(stats=stats, header=header, sections=section_diffs)


def diff_tex_sources(
    base_tex: str, head_tex: str, *, context: int = 2
) -> list[DiffRow]:
    """Line diff over LaTeX source, for the ``tex`` comparison mode."""
    base_lines = base_tex.splitlines()
    head_lines = head_tex.splitlines()
    rows: list[DiffRow] = []
    for base_index, head_index in _pair_strings(base_lines, head_lines):
        line_number = head_index if head_index is not None else base_index
        rows.append(
            _text_row(
                "line",
                f"tex[{line_number}]",
                base_lines[base_index] if base_index is not None else None,
                head_lines[head_index] if head_index is not None else None,
                DiffAnchor(index=line_number),
            )
        )
    return _trim_context(rows, context)


def merge_accepted(
    base: ResumeDocument, head: ResumeDocument, accepted_paths: set[str]
) -> ResumeDocument:
    """Take only the named changes from ``head``, leaving the rest at ``base``.

    Paths are the ones :func:`diff_documents` puts on its rows, which is the
    same grammar the AI change applier uses — so "accept these three bullets"
    is expressible without re-running the model.

    Only content leaves are selectable, because that is all AI tailoring
    edits: section and entry structure comes from ``base`` unchanged. A
    whole-list path (``…tags``, ``…groups[i].values``) is all-or-nothing;
    those are short values with no meaningful per-item provenance.
    """
    merged = base.model_copy(deep=True)
    head_sections = {section.key: section for section in head.sections}

    for section in merged.sections:
        source = head_sections.get(section.key)
        if source is None or source.kind is not section.kind:
            continue
        prefix = f"sections.{section.key}"

        if section.kind is SectionKind.TEXT:
            if f"{prefix}.text" in accepted_paths:
                section.text = source.text
        elif section.kind is SectionKind.TAGS:
            if f"{prefix}.tags" in accepted_paths:
                section.tags = list(source.tags)
        elif section.kind is SectionKind.GROUPS:
            for index, group in enumerate(section.groups):
                if (
                    index < len(source.groups)
                    and f"{prefix}.groups[{index}].values" in accepted_paths
                ):
                    group.values = list(source.groups[index].values)
        else:
            source_entries = {entry.id: entry for entry in source.entries}
            for index, entry in enumerate(section.entries):
                source_entry = source_entries.get(entry.id)
                if source_entry is None:
                    continue
                entry_prefix = f"{prefix}.entries[{index}]"
                if f"{entry_prefix}.summary" in accepted_paths:
                    entry.summary = source_entry.summary
                for bullet_index, bullet in enumerate(source_entry.bullets):
                    if f"{entry_prefix}.bullets[{bullet_index}].text" not in accepted_paths:
                        continue
                    if bullet_index < len(entry.bullets):
                        entry.bullets[bullet_index].text = bullet.text
                    else:
                        # An accepted bullet the AI appended past the original
                        # rows; keep its style as authored.
                        entry.bullets.append(bullet.model_copy(deep=True))
    return merged


def diff_value_lists(
    base: list[str],
    head: list[str],
    *,
    path: str,
    kind: RowKind = "bullet",
) -> list[DiffRow]:
    """Compare two lists of lines into rows, spans included.

    Used where a feature proposes a replacement for one list of content (an
    entry's bullets, a group's values) rather than a whole document — the AI
    regenerate flow. Same pairing and span rules as the document diff, so the
    UI renders both through one component.
    """
    rows: list[DiffRow] = []
    for base_index, head_index in _pair_strings(base, head):
        line = head_index if head_index is not None else base_index
        rows.append(
            _text_row(
                kind,
                f"{path}[{line}]",
                base[base_index] if base_index is not None else None,
                head[head_index] if head_index is not None else None,
                DiffAnchor(index=line),
            )
        )
    return rows
