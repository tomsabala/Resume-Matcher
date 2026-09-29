"""Deterministic resume-wizard copy.

Sections are pure data, so there is no per-section copy: a question about a
section falls back to ``section_generic``, a template parameterised by the
section's own heading. Only the fixed wizard steps (intro, contact, review)
have bespoke copy.
"""

_COPY: dict[str, str] = {
    "intro": "Hi — I'll help you build your master resume. What's your name, and what kind of role are you going for?",
    "contact": "What's the best email, phone, or links (LinkedIn / GitHub / site) to include?",
    "review": "Let's review what's here before we create your master resume.",
    "next": "What would you like to add next?",
    "section_generic": "Tell me about {heading}: what should this section include?",
    "warning_name": "Add your name — it's required to create your resume.",
    "warning_contact": "Add at least one contact method (email, phone, or a link).",
    "warning_section_empty": "{heading} is empty — skip only if that's intentional.",
}

WIZARD_COPY_KEYS: tuple[str, ...] = tuple(_COPY)


def wizard_copy(key: str) -> str:
    """Return deterministic wizard copy for ``key``."""
    return _COPY[key]


def section_question(heading: str) -> str:
    """Fallback question for any section, named by its heading."""
    return wizard_copy("section_generic").format(heading=heading)


def section_empty_warning(heading: str) -> str:
    """Review note that a section has no content yet."""
    return wizard_copy("warning_section_empty").format(heading=heading)
