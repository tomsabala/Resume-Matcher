"""Escaping for user text interpolated into LaTeX.

This is the security and correctness boundary of LaTeX export. Every
user-authored string goes through :func:`escape_tex`; template macros never
do. Without it a resume containing ``100% off`` silently comments out the rest
of the line, and ``\\input{/etc/passwd}`` is a file read.

:func:`escape_tex_rich` is the same boundary for the one field the frontend
edits as rich text (bullets, stored as sanitised HTML): it converts the
allowed tag set to LaTeX markup and escapes everything else.
"""

from __future__ import annotations

import html
import re

__all__ = ["escape_tex", "escape_tex_rich"]

# Backslash first: every other replacement introduces backslashes, so
# escaping it later would double-escape them.
#
# ``<``, ``>`` and ``|`` are not TeX-special, but OT1 Computer Modern — the
# reference CV's encoding — maps them to ``¡``, ``¿`` and ``—``. A skills line
# reading "Java | Python" would print em dashes without these rows.
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
    ("<", r"\textless{}"),
    (">", r"\textgreater{}"),
    ("|", r"\textbar{}"),
)

# Unicode the engine cannot typeset under the reference preamble: each of
# these fails the compile outright with "Unicode character ... not set up for
# use with LaTeX". Characters that already compile (→ ← ± × ÷ • ° – — … “ ” €
# £ § ¶ © ® ½ µ ·) are deliberately absent — mapping them would change
# glyphs that are already correct.
#
# Guillemets become typographic double quotes: no guillemet macro exists
# without ``fontenc[T1]``, and switching encoding would move every glyph away
# from the reference's OT1 Computer Modern.
_UNICODE: tuple[tuple[str, str], ...] = (
    ("↔", r"$\leftrightarrow$"),
    ("⇒", r"$\Rightarrow$"),
    ("⟶", r"$\longrightarrow$"),
    ("≥", r"$\geq$"),
    ("≤", r"$\leq$"),
    ("≈", r"$\approx$"),
    ("≠", r"$\neq$"),
    ("∞", r"$\infty$"),
    ("√", r"$\surd$"),
    ("★", r"$\bigstar$"),
    ("✓", r"$\checkmark$"),
    ("π", r"$\pi$"),
    ("α", r"$\alpha$"),
    ("β", r"$\beta$"),
    ("λ", r"$\lambda$"),
    ("∙", r"$\bullet$"),
    ("‣", r"$\triangleright$"),
    ("′", r"$'$"),
    ("″", r"$''$"),
    ("«", r"\textquotedblleft{}"),
    ("»", r"\textquotedblright{}"),
    ("\u2060", ""),
)

# One alternation, one pass: replacement values are themselves full of
# backslashes and dollars, so a second pass would re-escape them.
_PATTERN = re.compile(
    "|".join(re.escape(char) for char, _ in _REPLACEMENTS + _UNICODE)
)
_LOOKUP = dict(_REPLACEMENTS + _UNICODE)


def escape_tex(value: object) -> str:
    """Return ``value`` as LaTeX-safe text.

    Non-strings are stringified first, so a template can pass a number or
    ``None`` without a guard. The result is plain text: it contains no active
    LaTeX, whatever the input was.

    Unicode outside :data:`_UNICODE` (Hebrew, CJK, emoji) passes through
    verbatim and the engine rejects it by name. That is deliberate: the
    compile log names the offending character, which beats silently deleting
    a user's content.
    """
    if value is None:
        return ""
    return _PATTERN.sub(lambda match: _LOOKUP[match.group()], str(value))


# The tag set the frontend sanitiser allows (`lib/utils/html-sanitizer.ts`),
# plus the `p`/`br` structure TipTap emits. Anything else is dropped, inner
# text kept — the backend does not trust the client to have sanitised.
_TAG = re.compile(r"<\s*(/?)\s*([A-Za-z][A-Za-z0-9]*)([^>]*?)/?\s*>")
_HREF = re.compile(
    r"""href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE
)
_LINK_SCHEMES = ("http://", "https://", "mailto:", "tel:")

_GROUP_OPENERS: dict[str, str] = {
    "strong": r"\textbf{",
    "b": r"\textbf{",
    "em": r"\textit{",
    "i": r"\textit{",
    "u": r"\underline{",
}


def _link_href(attributes: str) -> str:
    """The safe href of an ``<a>`` tag, or an empty string.

    Only the schemes a resume link can legitimately use are honoured; a bare
    ``www.`` host is promoted to https. Everything else (``javascript:``,
    ``data:``, a relative path) yields no link at all, and the caller keeps
    the anchor's text unlinked.
    """
    match = _HREF.search(attributes)
    if match is None:
        return ""
    raw = html.unescape(match.group(1) or match.group(2) or match.group(3) or "")
    url = raw.strip()
    if not url:
        return ""
    lowered = url.lower()
    if lowered.startswith(_LINK_SCHEMES):
        return url
    if lowered.startswith("www."):
        return f"https://{url}"
    return ""


def escape_tex_rich(value: object) -> str:
    """Return sanitised rich-text HTML as LaTeX markup.

    Bullets are authored in TipTap and stored as HTML. Passing them through
    :func:`escape_tex` prints the tags: ``<strong>x</strong>`` becomes
    ``¡strong¿x¡/strong¿`` on the page. This converts the allowed tags to
    their LaTeX equivalents and escapes every other byte, so the LaTeX and
    HTML renderers agree on what a bullet says.

    The output is always brace-balanced: an unclosed tag is closed at the end
    and a stray close tag is ignored, because an unbalanced group would fail
    the compile.
    """
    if value is None:
        return ""
    source = str(value)

    out: list[str] = []
    # (tag name, closing text) for each group this function opened.
    stack: list[tuple[str, str]] = []
    # A paragraph boundary only becomes `\par` when another paragraph opens;
    # a trailing `</p>` must not leave vertical space behind.
    closed_paragraph = False
    position = 0

    def emit_text(segment: str) -> None:
        nonlocal closed_paragraph
        if not segment:
            return
        # Entities first: `&amp;` → `&` → `\&`, `&lt;` → `<` → `\textless{}`.
        text = escape_tex(html.unescape(segment))
        if text.strip():
            closed_paragraph = False
        out.append(text)

    for match in _TAG.finditer(source):
        emit_text(source[position : match.start()])
        position = match.end()
        is_close = bool(match.group(1))
        name = match.group(2).lower()
        attributes = match.group(3)

        if name == "br":
            out.append("\\\\ ")
            continue
        if name == "p":
            if is_close:
                closed_paragraph = True
            elif closed_paragraph:
                out.append(r"\par ")
                closed_paragraph = False
            continue

        if is_close:
            if any(tag == name for tag, _ in stack):
                while stack:
                    tag, closing = stack.pop()
                    out.append(closing)
                    if tag == name:
                        break
            continue

        opener = _GROUP_OPENERS.get(name)
        if opener is not None:
            out.append(opener)
            stack.append((name, "}"))
        elif name == "a":
            href = _link_href(attributes)
            if href:
                out.append(r"\href{" + escape_tex(href) + "}{")
                stack.append((name, "}"))
            else:
                # Unsafe or missing href: keep the words, drop the link.
                stack.append((name, ""))
        # Any other tag: dropped, its text kept.

    emit_text(source[position:])
    while stack:
        out.append(stack.pop()[1])
    return "".join(out)
