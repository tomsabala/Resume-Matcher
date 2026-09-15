"""Escaping for user text interpolated into LaTeX.

This is the security and correctness boundary of LaTeX export. Every
user-authored string goes through :func:`escape_tex`; template macros never
do. Without it a resume containing ``100% off`` silently comments out the rest
of the line, and ``\\input{/etc/passwd}`` is a file read.
"""

from __future__ import annotations

import re

__all__ = ["escape_tex"]

# Backslash first: every other replacement introduces backslashes, so
# escaping it later would double-escape them.
_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\\", r"\textbackslash{}"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("$", r"\$"),
    ("&", r"\&"),
    ("#", r"\#"),
    ("^", r"\textasciicircum{}"),
    ("_", r"\_"),
    ("~", r"\textasciitilde{}"),
    ("%", r"\%"),
)

_PATTERN = re.compile("|".join(re.escape(char) for char, _ in _REPLACEMENTS))
_LOOKUP = dict(_REPLACEMENTS)


def escape_tex(value: object) -> str:
    """Return ``value`` as LaTeX-safe text.

    Non-strings are stringified first, so a template can pass a number or
    ``None`` without a guard. The result is plain text: it contains no active
    LaTeX, whatever the input was.
    """
    if value is None:
        return ""
    return _PATTERN.sub(lambda match: _LOOKUP[match.group()], str(value))
