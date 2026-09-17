"""FastAPI application entry point."""

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Fix for Windows: Use ProactorEventLoop for subprocess support (Playwright)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logger = logging.getLogger(__name__)
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.ai_budget import operation_error_content
from app.config import settings
from app.database import DatabaseBusyError, db
from app.pdf import close_pdf_renderer, init_pdf_renderer
from app.routers import (
    applications_router,
    config_router,
    diff_router,
    enrichment_router,
    health_router,
    jobs_router,
    resume_wizard_router,
    resumes_router,
    tex_router,
    versions_router,
    workspaces_router,
)
from app.routers.resumes import drain_processing_cleanup_tasks
from app.tenancy import TenantMiddleware


def _configure_application_logging() -> None:
    """Set the application log level, and give it somewhere to go.

    Uvicorn's ``dictConfig`` configures only its own ``uvicorn*`` loggers and
    leaves the root logger bare, so an ``app.*`` record propagating to a
    handler-less root fell through to ``logging.lastResort`` — which drops
    anything below WARNING. Setting a level without attaching a handler
    therefore discarded every ``logger.info`` in the application, including the
    startup lines that report the effective tenant mode and the data
    migrations. One stderr handler, installed once, next to the level.
    """
    numeric_level = getattr(logging, settings.log_level, logging.INFO)
    app_logger = logging.getLogger("app")
    app_logger.setLevel(numeric_level)
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(levelname)s:     %(name)s - %(message)s")
        )
        app_logger.addHandler(handler)


_configure_application_logging()


_PURGE_INTERVAL_SECONDS = 3600


async def _purge_idle_anonymous_tenants() -> None:
    """Delete anonymous tenants that have gone quiet, then again every hour.

    An anonymous visitor's slate is disposable by design; without this, every
    one-off visit would accumulate on disk forever. Admin tenants are never
    touched. Runs only in header mode — in single mode there are no anonymous
    tenants to purge.
    """
    while True:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=settings.anonymous_retention_hours
        )
        try:
            deleted = await db.purge_idle_anonymous(cutoff.isoformat())
            if deleted:
                logger.info("Purged idle anonymous tenants: %s", deleted)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed sweep must not kill the loop: the next hour retries, and
            # the only cost of a miss is disk.
            logger.exception("Anonymous purge failed")
        await asyncio.sleep(_PURGE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # A typo in the instance env file would otherwise degrade silently to
    # single-tenant, which is indistinguishable from working until two
    # visitors see each other's resumes.
    logger.info(
        "Tenancy: mode=%s, anonymous retention=%dh",
        settings.tenant_mode,
        settings.anonymous_retention_hours,
    )
    # Migrate the schema and warm the workspace lookup before serving, so no
    # request pays cold start inside its own AI deadline.
    await db.ensure_ready()
    # Import a legacy TinyDB database into SQLite if present (idempotent).
    # Fail-fast on error: starting with an empty DB would look like data loss.
    from app.scripts.migrate_tinydb_to_sqlite import migrate as migrate_tinydb

    result = await migrate_tinydb()
    if result.get("status") == "migrated":
        logger.info("Startup data migration: %s", result)
    # Fold any legacy plaintext API keys into the encrypted store (idempotent,
    # non-clobbering), then strip them from config.json.
    from app.config import migrate_legacy_keys

    migrate_legacy_keys()
    purge_task: asyncio.Task[None] | None = None
    if settings.tenant_mode == "header":
        purge_task = asyncio.create_task(_purge_idle_anonymous_tenants())
    # PDF renderer uses lazy initialization - will initialize on first use
    # await init_pdf_renderer()
    yield
    if purge_task is not None:
        purge_task.cancel()
        try:
            await purge_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error stopping the anonymous purge task")

    # Shutdown - wrap each cleanup in try-except to ensure all resources are released
    try:
        await drain_processing_cleanup_tasks()
    except Exception:
        logger.exception("Error draining processing cleanup")

    try:
        await close_pdf_renderer()
    except Exception as e:
        logger.error(f"Error closing PDF renderer: {e}")

    try:
        await db.close()
    except Exception as e:
        logger.error(f"Error closing database: {e}")


app = FastAPI(
    title="Resume Matcher API",
    description="AI-powered resume tailoring for job descriptions",
    version=__version__,
    lifespan=lifespan,
)

@app.exception_handler(DatabaseBusyError)
async def database_busy_handler(request: Request, error: DatabaseBusyError) -> JSONResponse:
    logger.warning("Database write contention for %s", request.url.path, exc_info=error)
    return JSONResponse(
        status_code=503,
        content=operation_error_content(request, "Database is busy. Please retry shortly."),
        headers={"Retry-After": "1"},
    )


# Resolve the request's tenant before anything touches the database. Added
# *before* CORS on purpose: Starlette applies the last-added middleware
# outermost, so CORS stays outside this one and a tenant-less 404 still
# carries CORS headers instead of surfacing as an opaque browser error.
app.add_middleware(TenantMiddleware)

# CORS middleware - origins configurable via CORS_ORIGINS env var
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.effective_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(resumes_router, prefix="/api/v1")
app.include_router(tex_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(enrichment_router, prefix="/api/v1")
app.include_router(applications_router, prefix="/api/v1")
app.include_router(resume_wizard_router, prefix="/api/v1")
app.include_router(diff_router, prefix="/api/v1")
app.include_router(versions_router, prefix="/api/v1")
app.include_router(workspaces_router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Resume Matcher API",
        "version": __version__,
        "docs": "/docs",
    }


def main():
    """Entry point for the project.scripts console script."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )


if __name__ == "__main__":
    main()
