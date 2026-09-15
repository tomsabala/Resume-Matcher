"""Generate LaTeX source from a resume document.

Jinja2 with LaTeX-safe delimiters (``<< >>`` / ``<% %>``), because ``{{ }}``
collides with TeX grouping and would make every template unreadable.

``autoescape`` is off — HTML escaping would be wrong here — so the ``tex``
filter is mandatory on every interpolated user string. The templates apply it
at each site rather than relying on a global, which keeps the one place a
macro is *deliberately* unescaped visible.
"""

from __future__ import annotations

from functools import cache

from jinja2 import Environment, PackageLoader, StrictUndefined

from app.latex.escape import escape_tex
from app.schemas.document import Contact, ResumeDocument, Section, SectionKind

__all__ = ["LATEX_TEMPLATES", "render_document_tex"]

# Template id → file. Kept small and explicit: a resume template is a design
# decision, not a plugin point.
LATEX_TEMPLATES: dict[str, str] = {
    "tex-classic": "classic.tex.j2",
    "tex-compact": "compact.tex.j2",
}

# Contact kind → fontawesome5 macro. Anything unmapped renders text-only.
_CONTACT_ICONS: dict[str, str] = {
    "email": r"\faEnvelope",
    "phone": r"\faMobile",
    "github": r"\faGithub",
    "linkedin": r"\faLinkedin",
    "website": r"\faGlobe",
    "location": r"\faMapMarker",
}


class UnknownLatexTemplateError(ValueError):
    """Raised for a template id with no ``.tex.j2`` behind it."""


@cache
def _environment() -> Environment:
    environment = Environment(
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
        loader=PackageLoader("app.latex", "templates"),
    )
    environment.filters["tex"] = escape_tex
    environment.filters["contact_url"] = contact_url
    environment.filters["contact_icon"] = contact_icon
    return environment


def contact_icon(contact: Contact) -> str:
    """The fontawesome macro for a contact, or an empty string."""
    return _CONTACT_ICONS.get(contact.kind, "")


def contact_url(contact: Contact) -> str:
    """The href a contact links to.

    An explicit ``url`` wins; otherwise it is derived from the kind, so a
    user who typed only ``tom@example.com`` still gets a mailto link.
    """
    if contact.url:
        return contact.url
    value = contact.value.strip()
    if not value:
        return ""
    if contact.kind == "email":
        return f"mailto:{value}"
    if contact.kind == "phone":
        return "tel:" + "".join(ch for ch in value if ch.isdigit() or ch == "+")
    if contact.kind == "location":
        return ""
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def _renderable_sections(document: ResumeDocument) -> list[Section]:
    """Visible sections that actually have content for their kind."""
    sections: list[Section] = []
    for section in document.sections:
        if not section.visible:
            continue
        if section.kind is SectionKind.TEXT and not section.text.strip():
            continue
        if section.kind is SectionKind.ENTRIES and not section.entries:
            continue
        if section.kind is SectionKind.TAGS and not any(
            value.strip() for value in section.tags
        ):
            continue
        if section.kind is SectionKind.GROUPS and not any(
            value.strip() for group in section.groups for value in group.values
        ):
            continue
        sections.append(section)
    return sections


def render_document_tex(
    document: ResumeDocument,
    template_id: str = "tex-classic",
    settings: dict[str, object] | None = None,
) -> str:
    """Render ``document`` to LaTeX source.

    ``settings`` carries the same knobs the HTML renderer takes; templates
    read only the ones they support and ignore the rest.
    """
    filename = LATEX_TEMPLATES.get(template_id)
    if filename is None:
        raise UnknownLatexTemplateError(f"Unknown LaTeX template: {template_id}")

    return _environment().get_template(filename).render(
        document=document,
        header=document.header,
        sections=_renderable_sections(document),
        settings=settings or {},
        SectionKind=SectionKind,
    )
