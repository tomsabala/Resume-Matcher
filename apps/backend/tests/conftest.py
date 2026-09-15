"""Shared test fixtures for Resume Matcher backend tests."""

import copy
import os
import socket
import sys
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest


# Set DATA_DIR before pytest imports any test module. Several integration tests
# import app.main at module scope, which constructs Settings and the global
# Database during collection; a function fixture would be too late to protect
# developer state from those imports.
_ORIGINAL_DATA_DIR = os.environ.get("DATA_DIR")
_TEST_DATA_DIR_CONTEXT = tempfile.TemporaryDirectory(prefix="resume-matcher-tests-")
_TEST_DATA_DIR = Path(_TEST_DATA_DIR_CONTEXT.name)
os.environ["DATA_DIR"] = str(_TEST_DATA_DIR)

import app.config as _config_module  # noqa: E402 - DATA_DIR must be set first

_IMPORTED_CONFIG_FILE_PATH = _config_module.CONFIG_FILE_PATH


class UnexpectedNetworkAccess(RuntimeError):
    """Raised when a deterministic backend test attempts a real connection."""


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore the caller environment and remove session-level temporary data."""
    del config  # Hook argument is required by pytest but otherwise unused.
    if _ORIGINAL_DATA_DIR is None:
        os.environ.pop("DATA_DIR", None)
    else:
        os.environ["DATA_DIR"] = _ORIGINAL_DATA_DIR
    _TEST_DATA_DIR_CONTEXT.cleanup()


@pytest.fixture(scope="session")
def imported_config_file_path() -> Path:
    """Return config.py's path alias as captured immediately after safe import."""
    return _IMPORTED_CONFIG_FILE_PATH


@pytest.fixture(scope="session")
def backend_test_data_dir() -> Path:
    """Return the temporary DATA_DIR installed before application imports."""
    return _TEST_DATA_DIR


@pytest.fixture(autouse=True)
def deny_external_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make accidental provider traffic fail before opening a socket.

    ASGITransport and respx-backed HTTP tests do not open sockets and continue
    to exercise their real in-process transports. Tests requiring an actual
    network connection must explicitly replace this guard at their boundary.
    """

    def blocked_connection(*args: Any, **kwargs: Any) -> NoReturn:
        del args, kwargs
        raise UnexpectedNetworkAccess(
            "External network access blocked in deterministic backend tests"
        )

    monkeypatch.setattr(socket, "create_connection", blocked_connection)
    monkeypatch.setattr(socket.socket, "connect", blocked_connection)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_connection)
    yield


@pytest.fixture(autouse=True)
async def isolated_backend_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Any]:
    """Isolate config, crypto and every imported database alias per test."""
    import app.config as config_module
    import app.database as database_module
    from app import crypto
    from app.config_cache import invalidate_config_cache
    from app.database import Database

    test_data_dir = tmp_path / "data"
    test_db = Database(db_path=test_data_dir / "resume_matcher.db")

    monkeypatch.setattr(config_module.settings, "data_dir", test_data_dir)
    # Preserve compatibility with code/tests that still monkeypatch the legacy
    # name while guaranteeing old config implementations are safe during RED.
    monkeypatch.setattr(config_module, "CONFIG_FILE_PATH", test_data_dir / "config.json")
    monkeypatch.setattr(database_module, "db", test_db)

    # Modules such as routers and app.main import ``db`` by value. Patch every
    # alias already loaded during collection; modules imported later receive
    # app.database.db, which is already the isolated instance.
    for module_name, module in tuple(sys.modules.items()):
        if not module_name.startswith("app.") or module is None:
            continue
        if isinstance(getattr(module, "db", None), Database):
            monkeypatch.setattr(module, "db", test_db)

    # Mirror the app lifespan: schema + default workspace exist before the
    # first request, so deadline-sensitive tests measure handler work only.
    await test_db.ensure_ready()
    invalidate_config_cache()
    crypto.reset_cache()
    try:
        yield test_db
    finally:
        invalidate_config_cache()
        crypto.reset_cache()
        await test_db.close()


# ---------------------------------------------------------------------------
# Sample resume data — a full v2 ResumeDocument
# ---------------------------------------------------------------------------


def _entry(entry_id: str, **fields: Any) -> dict:
    """One ENTRIES row with every field present, so tests compare like-for-like."""
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


def _bullets(*texts: str) -> list[dict]:
    return [{"text": text, "style": "bullet"} for text in texts]


@pytest.fixture
def sample_resume() -> dict:
    """A realistic document matching the ``ResumeDocument`` schema."""
    return {
        "schemaVersion": 2,
        "header": {
            "name": "Jane Doe",
            "headline": "Senior Backend Engineer",
            "contacts": [
                {
                    "id": "c-email",
                    "kind": "email",
                    "label": "jane@example.com",
                    "value": "jane@example.com",
                    "url": "",
                },
                {
                    "id": "c-phone",
                    "kind": "phone",
                    "label": "+1-555-0100",
                    "value": "+1-555-0100",
                    "url": "",
                },
                {
                    "id": "c-location",
                    "kind": "location",
                    "label": "San Francisco, CA",
                    "value": "San Francisco, CA",
                    "url": "",
                },
                {
                    "id": "c-github",
                    "kind": "github",
                    "label": "",
                    "value": "github.com/janedoe",
                    "url": "",
                },
            ],
        },
        "sections": [
            {
                "id": "s-summary",
                "key": "summary",
                "heading": "Summary",
                "headingI18nKey": "resume.sections.summary",
                "kind": "text",
                "visible": True,
                "column": "main",
                "text": (
                    "Backend engineer with 6 years of experience building scalable "
                    "Python APIs and microservices."
                ),
                "entries": [],
                "tags": [],
                "groups": [],
            },
            {
                "id": "s-experience",
                "key": "experience",
                "heading": "Experience",
                "headingI18nKey": "resume.sections.experience",
                "kind": "entries",
                "visible": True,
                "column": "main",
                "text": "",
                "entries": [
                    _entry(
                        "e-acme",
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
                        "e-startupco",
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
                "tags": [],
                "groups": [],
            },
            {
                "id": "s-education",
                "key": "education",
                "heading": "Education",
                "headingI18nKey": "resume.sections.education",
                "kind": "entries",
                "visible": True,
                "column": "main",
                "text": "",
                "entries": [
                    _entry(
                        "e-mit",
                        title="MIT",
                        subtitle="B.S. Computer Science",
                        period="2014 - 2018",
                        summary="Graduated with honors, Dean's List",
                    )
                ],
                "tags": [],
                "groups": [],
            },
            {
                "id": "s-projects",
                "key": "projects",
                "heading": "Projects",
                "headingI18nKey": "resume.sections.projects",
                "kind": "entries",
                "visible": True,
                "column": "main",
                "text": "",
                "entries": [
                    _entry(
                        "e-openapi",
                        title="OpenAPI Generator",
                        subtitle="Creator & Maintainer",
                        period="Mar 2021 - Present",
                        bullets=_bullets(
                            "CLI tool generating API clients from OpenAPI specs",
                            "500+ GitHub stars, used by 30+ companies",
                        ),
                    )
                ],
                "tags": [],
                "groups": [],
            },
            {
                "id": "s-skills",
                "key": "skills",
                "heading": "Skills & Awards",
                "headingI18nKey": "resume.sections.skills",
                "kind": "groups",
                "visible": True,
                "column": "main",
                "text": "",
                "entries": [],
                "tags": [],
                "groups": [
                    {
                        "label": "Technical Skills",
                        "values": [
                            "Python",
                            "FastAPI",
                            "Docker",
                            "AWS",
                            "PostgreSQL",
                            "Redis",
                        ],
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
            },
        ],
    }


@pytest.fixture
def sample_resume_copy(sample_resume) -> dict:
    """Deep copy of sample_resume for mutation-safe tests."""
    return copy.deepcopy(sample_resume)


# ---------------------------------------------------------------------------
# Job-related fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_job_keywords() -> dict:
    """Extracted job keywords matching the LLM output format."""
    return {
        "required_skills": ["Python", "FastAPI", "Docker", "Kubernetes"],
        "preferred_skills": ["AWS", "Terraform", "GraphQL"],
        "experience_requirements": ["5+ years backend development"],
        "education_requirements": ["Bachelor's in CS or equivalent"],
        "key_responsibilities": [
            "Design and build scalable APIs",
            "Lead technical architecture decisions",
        ],
        "keywords": ["microservices", "CI/CD", "agile", "REST API"],
        "experience_years": 5,
        "seniority_level": "senior",
    }


@pytest.fixture
def sample_job_description() -> str:
    """A realistic job description text."""
    return (
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


# ---------------------------------------------------------------------------
# Master resume — used for alignment validation
# ---------------------------------------------------------------------------

@pytest.fixture
def master_resume(sample_resume) -> dict:
    """Master resume (source of truth) — same as sample_resume by default."""
    return copy.deepcopy(sample_resume)


# ---------------------------------------------------------------------------
# ResumeChange fixtures for diff-based tests
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_changes():
    """A set of ResumeChange dicts covering all action types."""
    from app.schemas.models import ResumeChange

    return [
        ResumeChange(
            path="sections.summary.text",
            action="replace",
            original="Backend engineer with 6 years of experience building scalable Python APIs and microservices.",
            value="Senior backend engineer with 6 years building scalable Python APIs, microservices, and cloud infrastructure on AWS.",
            reason="Added cloud/AWS keywords from JD",
        ),
        ResumeChange(
            path="sections.experience.entries[0].bullets[0].text",
            action="replace",
            original="Built REST APIs serving 50K requests/day using Python and FastAPI",
            value="Designed and built REST APIs serving 50K requests/day using Python, FastAPI, and Docker",
            reason="Added Docker keyword from JD",
        ),
        ResumeChange(
            path="sections.experience.entries[0].bullets",
            action="append",
            original=None,
            value="Implemented CI/CD pipelines with GitHub Actions reducing deploy time by 40%",
            reason="Added CI/CD keyword from JD",
        ),
        ResumeChange(
            path="sections.skills.groups[0].values",
            action="reorder",
            original=None,
            value=["Python", "FastAPI", "Docker", "AWS", "PostgreSQL", "Redis"],
            reason="Already in good order, no change needed",
        ),
    ]


# ---------------------------------------------------------------------------
# Isolated database — swap the global TinyDB singleton for a temp-file DB
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_db(isolated_backend_state: Any) -> Any:
    """Expose the default per-test real SQLite database to tests that need it."""
    return isolated_backend_state
