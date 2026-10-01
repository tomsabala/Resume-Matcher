"""Content-language detection for generated output.

The workspace's ``content_language`` is a default, not a verdict: a deck of
Hebrew prep cards can sit beside an English resume, so each generated artifact
takes its language from its own source text and falls back to the workspace
only when that text carries too few letters to judge.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.prompts import get_language_name

#: Unicode block per supported non-Latin content language. A third language is
#: one row here, one in ``LANGUAGE_NAMES`` and - if RTL - one in the frontend's
#: ``RTL_CONTENT_LANGUAGES``.
SCRIPT_RANGES: dict[str, tuple[int, int]] = {"he": (0x0590, 0x05FF)}

#: Fewer letters than this and the sample is noise: a heading, a date, "N/A".
MIN_SAMPLE_LETTERS = 20

#: Share of a sample's letters that must belong to one non-Latin script before
#: it decides the language. Hebrew prose stays far above this even when dense
#: with Latin tech terms, URLs and company names; English scores zero.
NON_LATIN_SHARE_THRESHOLD = 0.2


def _strings(value: Any) -> Iterator[str]:
    """Every string *value* inside a str / list / dict structure, recursively.

    Dictionary **keys** are skipped on purpose: they are English schema
    identifiers (``workExperience``, ``schemaVersion``) that would otherwise
    swamp the letter count of a Hebrew document. Pydantic models are not
    handled - callers pass ``model_dump(mode="json")`` or the raw dicts they
    already hold.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _strings(item)


def _script_of(ch: str) -> str | None:
    """``SCRIPT_RANGES`` code for a letter, ``"en"`` for ASCII Latin.

    Accented Latin and every other script are evidence of nothing and return
    ``None`` so they neither decide nor dilute the ratio.
    """
    code = ord(ch)
    for language, (low, high) in SCRIPT_RANGES.items():
        if low <= code <= high:
            return language
    return "en" if ch.isascii() else None


def contains_script(value: Any, language: str) -> bool:
    """True when any string inside ``value`` carries one letter of ``language``.

    The *any*-predicate, for the places where a single glyph is fatal (the
    Latin-only LaTeX preamble) rather than the places that want the dominant
    language.
    """
    span = SCRIPT_RANGES.get(language)
    if span is None:
        return False
    low, high = span
    return any(low <= ord(ch) <= high for text in _strings(value) for ch in text)


def detect_content_language(*samples: Any) -> str | None:
    """The language of the first sample carrying enough letters to judge.

    Returns a ``LANGUAGE_NAMES`` code, or ``None`` when no sample reaches
    ``MIN_SAMPLE_LETTERS`` - the caller then falls back to the workspace.
    """
    for sample in samples:
        counts: dict[str, int] = {}
        total = 0
        for text in _strings(sample):
            for ch in text:
                if not ch.isalpha():
                    continue
                script = _script_of(ch)
                if script is None:
                    continue
                counts[script] = counts.get(script, 0) + 1
                total += 1
        if total < MIN_SAMPLE_LETTERS:
            continue
        for language in SCRIPT_RANGES:
            if counts.get(language, 0) / total >= NON_LATIN_SHARE_THRESHOLD:
                return language
        return "en"
    return None


def output_language_for(*samples: Any, default: str) -> str:
    """The prompt-facing language name for the content being generated from.

    ``default`` is the workspace's content-language **code**; the return value
    is the **name** that ``{output_language}`` interpolates.
    """
    return get_language_name(detect_content_language(*samples) or default)
