"""Deterministic preservation at the final AI-authored resume seam.

Section-agnostic: the source document defines the contract, and the AI's
candidate is merged back onto it section by section. An entry's identity is
``(title, subtitle)`` and its protected fields are ``id, title, subtitle,
meta, period, links`` — one rule for every section, user-created ones
included, replacing the per-section field tables the v1 model needed.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any

from app.schemas.document import (
    Bullet,
    Entry,
    ResumeDocument,
    Section,
    SectionKind,
    TagGroup,
    migrate_document,
)

GROUNDING_REVIEW_CODE = "GROUNDING_REVIEW_REQUIRED"
_GROUNDING_REVIEW_THRESHOLD = 0.45

# Fields the AI may never rewrite: who, where and when.
_PROTECTED_ENTRY_FIELDS = ("id", "title", "subtitle", "meta", "period", "links")

_TOKEN_RE = re.compile(r"[\w+#./-]+", re.UNICODE)
_NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<currency>[$€£])?(?P<number>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<unit>thousand|million|billion|percent|times|ms|gb|mb|tb|[kmb%x]))?"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "the",
        "to",
        "using",
        "with",
    }
)


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(text)
        if len(token) > 1 and token.casefold() not in _STOP_WORDS
    }


def _similarity(left: str, right: str) -> float:
    left_normalized = _normalized(left)
    right_normalized = _normalized(right)
    if left_normalized == right_normalized:
        return 1.0
    left_tokens = _tokens(left_normalized)
    right_tokens = _tokens(right_normalized)
    overlap = len(left_tokens & right_tokens) / max(
        1, max(len(left_tokens), len(right_tokens))
    )
    sequence = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    if left_tokens < right_tokens or right_tokens < left_tokens:
        # Character similarity must not hide a material expansion or truncation
        # when every token on the shorter side happens to match.
        return overlap * sequence
    return max(overlap, sequence)


def _is_date_like_number(text: str, match: re.Match[str]) -> bool:
    """Return whether a bare four-digit number appears in date context."""
    prefix = text[max(0, match.start() - 24) : match.start()].casefold()
    suffix = text[match.end() : min(len(text), match.end() + 16)].casefold()
    month = (
        r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
        r"dec(?:ember)?)"
    )
    return bool(
        re.search(rf"\b{month}\s*$", prefix)
        or (
            re.search(
                r"\b(?:in|since|during|from|until|through|between)\s*$", prefix
            )
            and re.match(r"^\s*(?:$|[,.;:)])", suffix)
        )
        or re.search(r"\b\d{4}\s*[-–—/]\s*$", prefix)
        or re.match(r"^\s*[-–—/]\s*(?:\d{4}|present|current)\b", suffix)
    )


def _novel_numbers(source: str, candidate: str) -> bool:
    def numeric_claims(text: str) -> Counter[str]:
        claims: Counter[str] = Counter()
        for match in _NUMBER_RE.finditer(text):
            raw_number = match.group("number").replace(",", "")
            unit = (match.group("unit") or "").casefold()
            prefix = text[max(0, match.start() - 16) : match.start()].casefold()
            if re.search(r"(?:python|node(?:\.js)?|java|version|v)\s*$", prefix):
                continue
            if not unit and not match.group("currency"):
                try:
                    integer = int(raw_number)
                except ValueError:
                    integer = 0
                if 1900 <= integer <= 2100 and _is_date_like_number(text, match):
                    continue
            try:
                value = Decimal(raw_number)
            except InvalidOperation:
                continue
            scale = {
                "k": 1_000,
                "thousand": 1_000,
                "m": 1_000_000,
                "million": 1_000_000,
                "b": 1_000_000_000,
                "billion": 1_000_000_000,
            }.get(unit, 1)
            value *= scale
            normalized_value = format(value.normalize(), "f")
            kind = (
                match.group("currency")
                or ("%" if unit in {"%", "percent"} else "")
                or ("x" if unit in {"x", "times"} else "")
                or (unit if unit in {"ms", "gb", "mb", "tb"} else "")
            )
            claims[f"{kind}:{normalized_value}"] += 1
        return claims

    source_numbers = numeric_claims(source)
    candidate_numbers = numeric_claims(candidate)
    return any(
        count > source_numbers[value] for value, count in candidate_numbers.items()
    )


def _normalized_candidate_rows(value: Any) -> list[str]:
    """Strip stray newlines and bullet markers before preservation matching."""
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        for raw_line in re.split(r"\r?\n+", item):
            line = re.sub(r"^\s*(?:[-*•‣◦▪▫]+|\d+[.)])\s*", "", raw_line).strip()
            if line:
                rows.append(line)
    return rows


def _best_source_row(
    candidate: str,
    source_rows: list[str],
    available: set[int],
) -> tuple[int, float] | None:
    if not available:
        return None
    scored = [
        (_similarity(source_rows[index], candidate), index) for index in available
    ]
    score, index = max(scored, key=lambda item: (item[0], -item[1]))
    return index, score


def _entry_identity(entry: Entry) -> tuple[str, str]:
    """Who and where. One rule for every kind of entry."""
    return _normalized(entry.title), _normalized(entry.subtitle)


def _entry_text(entry: Entry) -> str:
    return " ".join([entry.summary, *(bullet.text for bullet in entry.bullets)])


def _matching_source_index(
    candidate: Entry,
    source_entries: list[Entry],
    available: set[int],
) -> int | None:
    """Pair a candidate entry with its source, by id then by identity."""
    if candidate.id:
        for index in sorted(available):
            if source_entries[index].id == candidate.id:
                return index

    identity = _entry_identity(candidate)
    if not any(identity):
        return None
    matches = [
        index
        for index in sorted(available)
        if _entry_identity(source_entries[index]) == identity
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    candidate_text = _entry_text(candidate)
    return max(
        matches,
        key=lambda index: (
            _similarity(_entry_text(source_entries[index]), candidate_text),
            -index,
        ),
    )


def _merge_bullets(
    source: Entry,
    candidate: Entry,
    *,
    allow_review_claims: bool,
    allow_appended_rows: bool,
) -> list[Bullet]:
    """Merge candidate bullet text onto the source's bullet rows.

    Each candidate row is paired with its closest unused source row; a row
    that is blank, invents a number, or (outside review mode) drifts too far
    from its source is restored. Style always comes from the source row, so a
    rewrite can never silently change a bullet into a paragraph. Unmatched
    source rows are appended, so a real bullet is never lost.
    """
    source_rows = source.bullets
    source_text = " ".join(bullet.text for bullet in source_rows)
    candidate_rows = _normalized_candidate_rows(
        [bullet.text for bullet in candidate.bullets]
    )
    source_texts = [bullet.text for bullet in source_rows]
    available = set(range(len(source_rows)))
    merged: list[Bullet] = []

    for candidate_index, row in enumerate(candidate_rows[: len(source_rows)]):
        match = _best_source_row(row, source_texts, available)
        if match is None:
            break
        source_index, score = match
        requires_restore = (
            not row.strip()
            or _novel_numbers(source_text, row)
            or (not allow_review_claims and score < _GROUNDING_REVIEW_THRESHOLD)
        )
        if not row.strip() and candidate_index in available:
            source_index = candidate_index
        available.remove(source_index)
        source_bullet = source_rows[source_index]
        merged.append(
            Bullet(
                text=source_bullet.text if requires_restore else row,
                style=source_bullet.style,
            )
        )

    for source_index in sorted(available):
        merged.append(source_rows[source_index].model_copy(deep=True))

    if allow_appended_rows:
        for row in candidate_rows[len(source_rows) :]:
            match = _best_source_row(row, source_texts, set(range(len(source_rows))))
            grounded = match is not None and match[1] >= _GROUNDING_REVIEW_THRESHOLD
            if _novel_numbers(source_text, row) or (
                not allow_review_claims and not grounded
            ):
                continue
            merged.append(Bullet(text=row, style="bullet"))
    return merged


def _merge_prose(
    source_text: str,
    candidate_text: str,
    *,
    allow_review_claims: bool,
) -> str:
    """Keep a rewrite only when it is non-empty and grounded in the source."""
    if not isinstance(candidate_text, str) or not candidate_text.strip():
        return source_text
    if _novel_numbers(source_text, candidate_text):
        return source_text
    if (
        not allow_review_claims
        and _similarity(source_text, candidate_text) < _GROUNDING_REVIEW_THRESHOLD
    ):
        return source_text
    return candidate_text


def _bullets_contract_preserved(
    source: Entry,
    candidate: Entry,
    *,
    allow_appended_rows: bool,
) -> bool:
    """Row count and per-row style must survive a confirm payload."""
    if len(candidate.bullets) < len(source.bullets):
        return False
    if not allow_appended_rows and len(candidate.bullets) != len(source.bullets):
        return False

    source_texts = [bullet.text for bullet in source.bullets]
    available = set(range(len(source.bullets)))
    for candidate_bullet in candidate.bullets[: len(source.bullets)]:
        match = _best_source_row(candidate_bullet.text, source_texts, available)
        if match is None:
            return False
        source_index, _ = match
        available.remove(source_index)
        if candidate_bullet.style != source.bullets[source_index].style:
            return False
    return True


def _merge_entries(
    source_entries: list[Entry],
    candidate_entries: list[Entry],
    *,
    allow_review_claims: bool,
    allow_appended_rows: bool,
) -> list[Entry]:
    """Rebuild the source's entry list, adopting grounded candidate prose."""
    result: list[Entry] = []
    available = set(range(len(source_entries)))
    for candidate in candidate_entries:
        source_index = _matching_source_index(candidate, source_entries, available)
        if source_index is None:
            continue
        available.remove(source_index)
        source = source_entries[source_index]
        merged = candidate.model_copy(deep=True)
        for field in _PROTECTED_ENTRY_FIELDS:
            setattr(merged, field, copy.deepcopy(getattr(source, field)))
        merged.summary = _merge_prose(
            source.summary, candidate.summary, allow_review_claims=allow_review_claims
        )
        merged.bullets = _merge_bullets(
            source,
            candidate,
            allow_review_claims=allow_review_claims,
            allow_appended_rows=allow_appended_rows,
        )
        result.append(merged)

    for source_index in sorted(available):
        result.append(source_entries[source_index].model_copy(deep=True))
    return result


def _merge_values(source_values: list[str], candidate_values: list[str]) -> list[str]:
    """Keep the candidate's order and additions; restore anything dropped.

    New short values can only reach a candidate through the verified
    ``add_skill`` gate in ``apply_diffs``, so they are trusted here. Removals
    are not: a source value the candidate omitted is appended back.
    """
    remaining = Counter(_normalized(value) for value in candidate_values)
    result = list(candidate_values)
    for value in source_values:
        key = _normalized(value)
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            result.append(value)
    return result


def _merge_groups(
    source_groups: list[TagGroup], candidate_groups: list[TagGroup]
) -> list[TagGroup]:
    """Merge labelled groups; labels come from the source, values are merged."""
    candidate_by_label = {
        _normalized(group.label): group for group in candidate_groups
    }
    return [
        TagGroup(
            label=group.label,
            values=_merge_values(
                group.values,
                candidate_by_label[_normalized(group.label)].values
                if _normalized(group.label) in candidate_by_label
                else [],
            ),
        )
        for group in source_groups
    ]


def _merge_section(
    source: Section,
    candidate: Section | None,
    *,
    allow_review_claims: bool,
    allow_appended_rows: bool,
) -> Section:
    """Merge one candidate section onto its source, by kind."""
    merged = source.model_copy(deep=True)
    if candidate is None or candidate.kind is not source.kind:
        return merged

    if source.kind is SectionKind.TEXT:
        merged.text = _merge_prose(
            source.text, candidate.text, allow_review_claims=allow_review_claims
        )
    elif source.kind is SectionKind.ENTRIES:
        merged.entries = _merge_entries(
            source.entries,
            candidate.entries,
            allow_review_claims=allow_review_claims,
            allow_appended_rows=allow_appended_rows,
        )
    elif source.kind is SectionKind.TAGS:
        merged.tags = _merge_values(source.tags, candidate.tags)
    else:
        merged.groups = _merge_groups(source.groups, candidate.groups)
    return merged


def finalize_ai_resume(
    source: dict[str, Any],
    candidate: dict[str, Any],
    *,
    allow_review_claims: bool = True,
    allow_appended_rows: bool = False,
) -> dict[str, Any]:
    """Return a non-mutating AI result that preserves the source contract.

    Weakly grounded rewrites remain when ``allow_review_claims`` is true so a
    preview can present them for explicit confirmation. Definite new metrics,
    extra rows, missing sections and identity drift are always repaired.

    The source document defines which sections exist: the header is restored
    wholesale and a section the AI invented is dropped, because tailoring
    edits content and never authors structure.
    """
    source_document = migrate_document(source)
    candidate_document = migrate_document(candidate)
    candidate_by_key = {
        section.key: section for section in candidate_document.sections
    }
    result = ResumeDocument(
        header=source_document.header.model_copy(deep=True),
        sections=[
            _merge_section(
                section,
                candidate_by_key.get(section.key),
                allow_review_claims=allow_review_claims,
                allow_appended_rows=allow_appended_rows,
            )
            for section in source_document.sections
        ],
    )
    return result.model_dump(mode="json")


def _entry_buckets(entries: list[Entry]) -> dict[tuple[str, str], list[Entry]]:
    buckets: dict[tuple[str, str], list[Entry]] = {}
    for entry in entries:
        buckets.setdefault(_entry_identity(entry), []).append(entry)
    return buckets


def _entry_bucket_violation(
    source_entries: list[Entry],
    candidate_entries: list[Entry],
    *,
    allow_appended_rows: bool,
) -> str | None:
    """Validate one identity bucket using the finalizer's content matching."""
    available = set(range(len(source_entries)))
    for candidate in candidate_entries:
        source_index = _matching_source_index(candidate, source_entries, available)
        if source_index is None:
            return "identity"
        available.remove(source_index)
        source = source_entries[source_index]
        if any(
            getattr(source, field) != getattr(candidate, field)
            for field in _PROTECTED_ENTRY_FIELDS
        ):
            return "identity"
        if not _bullets_contract_preserved(
            source, candidate, allow_appended_rows=allow_appended_rows
        ):
            return "descriptions"
    return None


def validate_confirmed_resume(
    source: dict[str, Any],
    candidate: dict[str, Any],
    *,
    allow_appended_rows: bool = False,
) -> list[str]:
    """Return stable source-contract violation codes for a confirm payload."""
    source_document = migrate_document(source)
    candidate_document = migrate_document(candidate)
    candidate_by_key = {
        section.key: section for section in candidate_document.sections
    }
    violations: list[str] = []

    for section in source_document.sections:
        path = f"sections.{section.key}"
        candidate_section = candidate_by_key.get(section.key)
        if candidate_section is None or candidate_section.kind is not section.kind:
            violations.append(path)
            continue

        if section.kind is SectionKind.TEXT:
            if section.text.strip() and not _normalized(candidate_section.text):
                violations.append(f"{path}.text")
        elif section.kind is SectionKind.ENTRIES:
            source_buckets = _entry_buckets(section.entries)
            candidate_buckets = _entry_buckets(candidate_section.entries)
            if Counter(
                {key: len(value) for key, value in source_buckets.items()}
            ) != Counter(
                {key: len(value) for key, value in candidate_buckets.items()}
            ):
                violations.append(f"{path}.entries")
                continue
            for key, entries in source_buckets.items():
                violation = _entry_bucket_violation(
                    entries,
                    candidate_buckets[key],
                    allow_appended_rows=allow_appended_rows,
                )
                if violation is not None:
                    violations.append(f"{path}.{violation}")
        elif section.kind is SectionKind.TAGS:
            if _missing_values(section.tags, candidate_section.tags):
                violations.append(f"{path}.tags")
        else:
            candidate_by_label = {
                _normalized(group.label): group for group in candidate_section.groups
            }
            for index, group in enumerate(section.groups):
                other = candidate_by_label.get(_normalized(group.label))
                if other is None or _missing_values(group.values, other.values):
                    violations.append(f"{path}.groups[{index}]")

    return list(dict.fromkeys(violations))


def _missing_values(source_values: list[str], candidate_values: list[str]) -> bool:
    """True when the candidate dropped a source value (additions are allowed)."""
    source_counts = Counter(_normalized(value) for value in source_values)
    candidate_counts = Counter(_normalized(value) for value in candidate_values)
    return bool(source_counts - candidate_counts)


def _grounding_warning(path: str) -> str:
    return f"{GROUNDING_REVIEW_CODE}: Review {path} against the source resume."


def _bullet_grounding_warnings(
    source: Entry, candidate: Entry, path: str
) -> list[str]:
    """Flag candidate bullets whose overlap with their source row is weak."""
    warnings: list[str] = []
    source_texts = [bullet.text for bullet in source.bullets]
    available = set(range(len(source_texts)))
    assignments: dict[int, tuple[int, float]] = {}

    # Exact matches first so a reordered-but-identical row never looks novel.
    for row_index, bullet in enumerate(candidate.bullets):
        exact = next(
            (
                index
                for index in sorted(available)
                if _normalized(source_texts[index]) == _normalized(bullet.text)
            ),
            None,
        )
        if exact is not None:
            assignments[row_index] = (exact, 1.0)
            available.remove(exact)

    for row_index, bullet in enumerate(candidate.bullets):
        if row_index in assignments:
            continue
        match = _best_source_row(bullet.text, source_texts, available)
        if match is None:
            continue
        source_index, score = match
        available.remove(source_index)
        assignments[row_index] = (source_index, score)

    for row_index, bullet in enumerate(candidate.bullets):
        assignment = assignments.get(row_index)
        if assignment is None:
            match = _best_source_row(
                bullet.text, source_texts, set(range(len(source_texts)))
            )
            if _normalized(bullet.text) and (
                match is None or match[1] < _GROUNDING_REVIEW_THRESHOLD
            ):
                warnings.append(_grounding_warning(f"{path}.bullets[{row_index}]"))
            continue
        source_index, score = assignment
        if (
            _normalized(bullet.text) != _normalized(source_texts[source_index])
            and score < _GROUNDING_REVIEW_THRESHOLD
        ):
            warnings.append(_grounding_warning(f"{path}.bullets[{row_index}]"))
    return warnings


def grounding_review_warnings(
    source: dict[str, Any], candidate: dict[str, Any]
) -> list[str]:
    """Return stable warnings for narrative rewrites with weak source overlap."""
    source_document = migrate_document(source)
    candidate_document = migrate_document(candidate)
    candidate_by_key = {
        section.key: section for section in candidate_document.sections
    }
    warnings: list[str] = []

    for section in source_document.sections:
        other = candidate_by_key.get(section.key)
        if other is None or other.kind is not section.kind:
            continue
        path = f"sections.{section.key}"

        if section.kind is SectionKind.TEXT:
            if (
                _normalized(section.text) != _normalized(other.text)
                and _similarity(section.text, other.text) < _GROUNDING_REVIEW_THRESHOLD
            ):
                warnings.append(_grounding_warning(f"{path}.text"))
            continue

        if section.kind is not SectionKind.ENTRIES:
            continue

        available = set(range(len(section.entries)))
        for candidate_index, candidate_entry in enumerate(other.entries):
            source_index = _matching_source_index(
                candidate_entry, section.entries, available
            )
            if source_index is None:
                continue
            available.remove(source_index)
            source_entry = section.entries[source_index]
            entry_path = f"{path}.entries[{candidate_index}]"
            if (
                _normalized(source_entry.summary) != _normalized(candidate_entry.summary)
                and _similarity(source_entry.summary, candidate_entry.summary)
                < _GROUNDING_REVIEW_THRESHOLD
            ):
                warnings.append(_grounding_warning(f"{entry_path}.summary"))
            warnings.extend(
                _bullet_grounding_warnings(source_entry, candidate_entry, entry_path)
            )
    return warnings
