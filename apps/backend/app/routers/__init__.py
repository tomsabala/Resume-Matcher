"""API routers."""

from app.routers.applications import router as applications_router
from app.routers.config import router as config_router
from app.routers.diff import router as diff_router
from app.routers.enrichment import router as enrichment_router
from app.routers.health import router as health_router
from app.routers.jobs import router as jobs_router
from app.routers.resume_wizard import router as resume_wizard_router
from app.routers.resumes import router as resumes_router
from app.routers.tex import router as tex_router
from app.routers.versions import router as versions_router
from app.routers.workspaces import router as workspaces_router

__all__ = [
    "resumes_router",
    "tex_router",
    "jobs_router",
    "config_router",
    "diff_router",
    "health_router",
    "enrichment_router",
    "applications_router",
    "resume_wizard_router",
    "versions_router",
    "workspaces_router",
]
