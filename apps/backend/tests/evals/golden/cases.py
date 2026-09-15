"""Golden fixtures for the eval harness.

Each entry in :data:`GOLDEN_CASES` bundles everything the two eval layers need
for one realistic tailoring scenario:

* ``name``            — a short, human-readable id.
* ``original``        — the master resume document (``ResumeDocument`` shaped).
* ``job_description`` — the target JD text.
* ``jd_keywords``     — all target JD keywords for coverage measurement.
* ``grounded_keywords`` — source-supported terms expected in a positive fixture.
* ``tailored_good``   — a faithful, JD-aware tailoring of ``original``. Every
                        section is preserved, no entries are invented, and
                        the source-supported target keywords appear. Structural scorers
                        should accept it; the paid judge evaluates newly
                        generated output, not this fixture.
* ``tailored_bad``    — a deliberately broken tailoring (drops a section,
                        invents an employer, rewrites the candidate's name).
                        Structural scorers MUST flag it. It exists so the
                        scorer tests can prove they detect real violations
                        rather than always returning "OK".

These are plain Python constants — no I/O, no LLM. To add a new golden case,
append another dict with the same keys to ``GOLDEN_CASES``. Keep ``original``
and ``tailored_good`` valid against ``app.schemas.document.ResumeDocument``
(schema version 2, unknown fields forbidden) so ``is_valid_resume`` stays
meaningful.
"""

from __future__ import annotations

from typing import Any


def _bullets(*texts: str) -> list[dict[str, Any]]:
    return [{"text": text, "style": "bullet"} for text in texts]


def _entry(entry_id: str, **fields: Any) -> dict[str, Any]:
    return {"id": entry_id, **fields}


def _section(key: str, heading: str, kind: str, **content: Any) -> dict[str, Any]:
    return {"id": f"s-{key}", "key": key, "heading": heading, "kind": kind, **content}


def _document(name: str, headline: str, contacts: list[dict[str, Any]],
              sections: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "header": {"name": name, "headline": headline, "contacts": contacts},
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Case 1 — backend engineer targeting a senior platform role
# ---------------------------------------------------------------------------

_CASE1_CONTACTS: list[dict[str, Any]] = [
    {"id": "c1-email", "kind": "email", "label": "jane@example.com",
     "value": "jane@example.com"},
    {"id": "c1-phone", "kind": "phone", "label": "+1-555-0100",
     "value": "+1-555-0100"},
    {"id": "c1-location", "kind": "location", "label": "San Francisco, CA",
     "value": "San Francisco, CA"},
    {"id": "c1-website", "kind": "website", "label": "janedoe.dev",
     "value": "https://janedoe.dev"},
    # github/linkedin render icon-only, so their label is deliberately empty.
    {"id": "c1-linkedin", "kind": "linkedin", "label": "",
     "value": "linkedin.com/in/janedoe"},
    {"id": "c1-github", "kind": "github", "label": "", "value": "github.com/janedoe"},
]

_CASE1_EDUCATION = _section(
    "education",
    "Education",
    "entries",
    entries=[
        _entry(
            "e1-mit",
            title="MIT",
            subtitle="B.S. Computer Science",
            period="2014 - 2018",
            summary="Graduated with honors, Dean's List",
        )
    ],
)

_CASE1_PROJECTS = _section(
    "projects",
    "Projects",
    "entries",
    entries=[
        _entry(
            "e1-openapi",
            title="OpenAPI Generator",
            subtitle="Creator & Maintainer",
            period="Mar 2021 - Present",
            bullets=_bullets(
                "CLI tool generating API clients from OpenAPI specs",
                "500+ GitHub stars, used by 30+ companies",
            ),
        )
    ],
)

_CASE1_SKILLS = _section(
    "skills",
    "Skills & Awards",
    "groups",
    groups=[
        {
            "label": "Technical Skills",
            "values": ["Python", "FastAPI", "Docker", "AWS", "PostgreSQL", "Redis"],
        },
        {
            "label": "Languages",
            "values": ["English (Native)", "Spanish (Conversational)"],
        },
        {
            "label": "Certifications & Training",
            "values": ["AWS Solutions Architect Associate"],
        },
        {"label": "Awards", "values": ["Employee of the Year 2022"]},
    ],
)

_CASE1_ORIGINAL: dict[str, Any] = _document(
    "Jane Doe",
    "Senior Backend Engineer",
    _CASE1_CONTACTS,
    [
        _section(
            "summary",
            "Summary",
            "text",
            text=(
                "Backend engineer with 6 years of experience building scalable "
                "Python APIs and microservices."
            ),
        ),
        _section(
            "experience",
            "Experience",
            "entries",
            entries=[
                _entry(
                    "e1-acme",
                    title="Senior Backend Engineer",
                    subtitle="Acme Corp",
                    meta="San Francisco, CA",
                    period="Jan 2021 - Present",
                    bullets=_bullets(
                        "Built REST APIs serving 50K requests/day using Python and FastAPI",
                        "Led migration from monolith to microservices architecture",
                        "Mentored 3 junior developers on backend best practices",
                    ),
                ),
                _entry(
                    "e1-startupco",
                    title="Software Engineer",
                    subtitle="StartupCo",
                    meta="New York, NY",
                    period="Jun 2018 - Dec 2020",
                    bullets=_bullets(
                        "Developed payment processing system handling $2M monthly",
                        "Wrote unit and integration tests improving coverage from 40% to 85%",
                    ),
                ),
            ],
        ),
        _CASE1_EDUCATION,
        _CASE1_PROJECTS,
        _CASE1_SKILLS,
    ],
)

_CASE1_JD: str = (
    "Senior Backend Engineer at TechCorp\n\n"
    "We are looking for a Senior Backend Engineer to join our platform team. "
    "You will design and build scalable APIs using Python and FastAPI. "
    "Experience with Docker, Kubernetes, and AWS is required. "
    "Terraform and GraphQL experience is a plus.\n\n"
    "Requirements:\n"
    "- 5+ years backend development experience\n"
    "- Strong Python skills with FastAPI or similar frameworks\n"
    "- Experience with microservices architecture\n"
    "- Familiarity with CI/CD pipelines and agile methodologies\n"
    "- Bachelor's degree in CS or equivalent\n"
)

# A faithful tailoring preserves stated evidence. Migration work alone does
# not establish Kubernetes or CI/CD experience; those target terms stay absent.
_CASE1_TAILORED_GOOD: dict[str, Any] = _document(
    "Jane Doe",
    "Senior Backend Engineer",
    _CASE1_CONTACTS,
    [
        _section(
            "summary",
            "Summary",
            "text",
            text=(
                "Senior backend engineer with 6 years building scalable Python and "
                "FastAPI APIs and microservices, with Docker "
                "and AWS skills."
            ),
        ),
        _section(
            "experience",
            "Experience",
            "entries",
            entries=[
                _entry(
                    "e1-acme",
                    title="Senior Backend Engineer",
                    subtitle="Acme Corp",
                    meta="San Francisco, CA",
                    period="Jan 2021 - Present",
                    bullets=_bullets(
                        "Built REST APIs serving 50K requests/day using Python and FastAPI",
                        "Led migration from a monolith to a microservices architecture",
                        "Mentored 3 junior developers on backend best practices",
                    ),
                ),
                _entry(
                    "e1-startupco",
                    title="Software Engineer",
                    subtitle="StartupCo",
                    meta="New York, NY",
                    period="Jun 2018 - Dec 2020",
                    bullets=_bullets(
                        "Developed a payment processing system handling $2M monthly",
                        "Wrote unit and integration tests improving coverage from 40% to 85%",
                    ),
                ),
            ],
        ),
        _CASE1_EDUCATION,
        _CASE1_PROJECTS,
        _CASE1_SKILLS,
    ],
)

# A broken tailoring: identity rewritten, education dropped, and a fabricated
# employer ("Globex Industries") inserted into the experience section.
_CASE1_TAILORED_BAD: dict[str, Any] = _document(
    "John Smith",  # identity changed — must be flagged
    "Senior Backend Engineer",
    _CASE1_CONTACTS,
    [
        _section(
            "summary",
            "Summary",
            "text",
            text=(
                "Senior backend engineer with Python, FastAPI, Kubernetes, Docker, "
                "AWS, and CI/CD experience."
            ),
        ),
        # Real employers replaced by a never-held one.
        _section(
            "experience",
            "Experience",
            "entries",
            entries=[
                _entry(
                    "e1-globex",
                    title="Principal Engineer",
                    subtitle="Globex Industries",  # fabricated employer
                    meta="Remote",
                    period="Jan 2015 - Present",
                    bullets=_bullets("Owned the entire platform on Kubernetes and AWS"),
                )
            ],
        ),
        # Education emptied — must be flagged.
        _section("education", "Education", "entries", entries=[]),
        _CASE1_PROJECTS,
        _section(
            "skills",
            "Skills & Awards",
            "groups",
            groups=[
                {
                    "label": "Technical Skills",
                    "values": ["Python", "FastAPI", "Kubernetes", "Docker", "AWS"],
                }
            ],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Case 2 — data analyst pivoting toward a data-engineering role
# ---------------------------------------------------------------------------

_CASE2_CONTACTS: list[dict[str, Any]] = [
    {"id": "c2-email", "kind": "email", "label": "carlos@example.com",
     "value": "carlos@example.com"},
    {"id": "c2-phone", "kind": "phone", "label": "+1-555-0199",
     "value": "+1-555-0199"},
    {"id": "c2-location", "kind": "location", "label": "Austin, TX",
     "value": "Austin, TX"},
    {"id": "c2-linkedin", "kind": "linkedin", "label": "",
     "value": "linkedin.com/in/carlosreyes"},
]

_CASE2_EDUCATION = _section(
    "education",
    "Education",
    "entries",
    entries=[
        _entry(
            "e2-utaustin",
            title="University of Texas at Austin",
            subtitle="B.A. Economics",
            period="2016 - 2020",
            summary="Minor in Statistics",
        )
    ],
)

_CASE2_ORIGINAL: dict[str, Any] = _document(
    "Carlos Reyes",
    "Data Analyst",
    _CASE2_CONTACTS,
    [
        _section(
            "summary",
            "Summary",
            "text",
            text=(
                "Data analyst with 4 years turning messy datasets into dashboards "
                "and reports that drive product decisions."
            ),
        ),
        _section(
            "experience",
            "Experience",
            "entries",
            entries=[
                _entry(
                    "e2-retailworks",
                    title="Data Analyst",
                    subtitle="RetailWorks",
                    meta="Austin, TX",
                    period="Feb 2022 - Present",
                    bullets=_bullets(
                        "Built weekly KPI dashboards in SQL and Tableau for 200+ stakeholders",
                        "Automated recurring reports, cutting manual effort by 12 hours/week",
                    ),
                ),
                _entry(
                    "e2-insightlabs",
                    title="Junior Analyst",
                    subtitle="Insight Labs",
                    meta="Austin, TX",
                    period="Aug 2020 - Jan 2022",
                    bullets=_bullets(
                        "Cleaned and modeled survey data for 30+ client studies",
                        "Wrote Python scripts to validate data quality before analysis",
                    ),
                ),
            ],
        ),
        _CASE2_EDUCATION,
        _section(
            "skills",
            "Skills",
            "groups",
            groups=[
                {
                    "label": "Technical Skills",
                    "values": ["SQL", "Python", "Tableau", "Excel", "pandas"],
                },
                {
                    "label": "Languages",
                    "values": ["English (Native)", "Spanish (Native)"],
                },
            ],
        ),
    ],
)

_CASE2_JD: str = (
    "Data Engineer at DataFlow Inc.\n\n"
    "We need a Data Engineer to build and maintain our analytics pipelines. "
    "You will write SQL and Python, build ETL workflows with Airflow, and "
    "model data in a cloud warehouse such as Snowflake or BigQuery.\n\n"
    "Requirements:\n"
    "- Strong SQL and Python\n"
    "- Experience building ETL/data pipelines\n"
    "- Comfort with data modeling and data quality\n"
    "- Bonus: dbt, Airflow, Snowflake\n"
)

# Faithful tailoring: same employers/identity, reframes the existing SQL/Python
# and data-quality work without inventing tools or assigning them to a role.
_CASE2_TAILORED_GOOD: dict[str, Any] = _document(
    "Carlos Reyes",
    "Data Analyst",
    _CASE2_CONTACTS,
    [
        _section(
            "summary",
            "Summary",
            "text",
            text=(
                "Data analyst with 4 years turning datasets into dashboards and "
                "reports, using SQL, Python and data quality checks to support "
                "reporting and product decisions."
            ),
        ),
        _section(
            "experience",
            "Experience",
            "entries",
            entries=[
                _entry(
                    "e2-retailworks",
                    title="Data Analyst",
                    subtitle="RetailWorks",
                    meta="Austin, TX",
                    period="Feb 2022 - Present",
                    bullets=_bullets(
                        "Built weekly KPI dashboards in SQL and Tableau for 200+ stakeholders",
                        "Automated recurring reports, cutting manual effort by 12 hours/week",
                    ),
                ),
                _entry(
                    "e2-insightlabs",
                    title="Junior Analyst",
                    subtitle="Insight Labs",
                    meta="Austin, TX",
                    period="Aug 2020 - Jan 2022",
                    bullets=_bullets(
                        "Cleaned and modeled survey data for 30+ client studies",
                        "Wrote Python scripts to enforce data quality before analysis",
                    ),
                ),
            ],
        ),
        _CASE2_EDUCATION,
        _section(
            "skills",
            "Skills",
            "groups",
            groups=[
                {
                    "label": "Technical Skills",
                    "values": [
                        "SQL",
                        "Python",
                        "data modeling",
                        "Tableau",
                        "Excel",
                        "pandas",
                    ],
                },
                {
                    "label": "Languages",
                    "values": ["English (Native)", "Spanish (Native)"],
                },
            ],
        ),
    ],
)

# Broken tailoring: real employers replaced by a fabricated one, work history
# effectively wiped, identity name altered.
_CASE2_TAILORED_BAD: dict[str, Any] = _document(
    "Carlos R. Mendez",  # identity changed
    "Data Analyst",
    _CASE2_CONTACTS,
    [
        _section(
            "summary",
            "Summary",
            "text",
            text=(
                "Data engineer with SQL, Python, Airflow, dbt, and Snowflake "
                "experience."
            ),
        ),
        _section(
            "experience",
            "Experience",
            "entries",
            entries=[
                _entry(
                    "e2-dataflow",
                    title="Senior Data Engineer",
                    subtitle="DataFlow Systems",  # fabricated employer (never held)
                    meta="Remote",
                    period="Jan 2019 - Present",
                    bullets=_bullets(
                        "Owned ETL pipelines on Snowflake with Airflow and dbt"
                    ),
                )
            ],
        ),
        _CASE2_EDUCATION,
        _section(
            "skills",
            "Skills",
            "groups",
            groups=[
                {
                    "label": "Technical Skills",
                    "values": ["SQL", "Python", "Airflow", "dbt", "Snowflake"],
                }
            ],
        ),
    ],
)


GOLDEN_CASES: list[dict[str, Any]] = [
    {
        "name": "backend_engineer_platform_role",
        "original": _CASE1_ORIGINAL,
        "job_description": _CASE1_JD,
        "jd_keywords": [
            "Python",
            "FastAPI",
            "Docker",
            "Kubernetes",
            "AWS",
            "microservices",
            "CI/CD",
        ],
        "grounded_keywords": ["Python", "FastAPI", "Docker", "AWS", "microservices"],
        "tailored_good": _CASE1_TAILORED_GOOD,
        "tailored_bad": _CASE1_TAILORED_BAD,
    },
    {
        "name": "data_analyst_to_data_engineer",
        "original": _CASE2_ORIGINAL,
        "job_description": _CASE2_JD,
        "jd_keywords": ["SQL", "Python", "ETL", "data quality", "data modeling"],
        "grounded_keywords": ["SQL", "Python", "data quality", "Tableau"],
        "tailored_good": _CASE2_TAILORED_GOOD,
        "tailored_bad": _CASE2_TAILORED_BAD,
    },
]
