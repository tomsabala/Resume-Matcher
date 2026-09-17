"""Request-scoped tenant identity.

One instance of this app can serve many visitors. The identity comes from an
upstream gateway, which authenticates the visitor and injects two headers on
every proxied request:

* ``X-Apps-Tenant`` — an opaque identity ref (the gateway's ``anon-<16 hex>`` /
  ``admin-<16 hex>``, treated here as a plain string).
* ``X-Apps-Role`` — ``admin`` for a whitelisted operator, anything else is
  anonymous.

``TenantMiddleware`` resolves that pair to an :class:`ActiveTenant` **once per
request**, in the same task that runs the endpoint, and publishes it on a
``ContextVar``. Resolving it in middleware rather than a FastAPI dependency is
what lets the request-context-free paths see the tenant too: the synchronous
config cache and the LLM key lookup are reached from
``get_llm_config`` → ``load_config_file``, which take no ``Request``.

Scoping itself never uses ``tenant_ref``. Every document table is scoped by
``workspace_id`` alone; ``workspaces.tenant_ref`` groups the workspaces one
identity owns, so the multi-profile feature survives per tenant.

This module deliberately imports nothing from ``app.database``,
``app.config_cache`` or ``app.llm`` at import time: it is the leaf every one of
those layers imports.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from app.config import settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

TENANT_HEADER = "x-apps-tenant"
ROLE_HEADER = "x-apps-role"
WORKSPACE_HEADER = "x-workspace-id"

#: The tenant every row carries in ``single`` mode, and the one the first
#: ``admin`` request claims when an instance is flipped to ``header`` mode.
SINGLE_TENANT_REF = ""

TenantRole = Literal["anon", "admin"]

# Paths that must answer without a tenant: the container healthcheck hits
# /api/v1/health, and the docs are how the operator inspects a live instance.
# GET /status is *not* exempt — it reports the caller's own resume stats.
EXEMPT_PATHS = frozenset({"/", "/docs", "/redoc", "/openapi.json", "/api/v1/health"})

# One `UPDATE workspaces SET last_seen_at` per request would be pure WAL
# amplification: the purge threshold is hours, so a coarse stamp is enough.
_TOUCH_INTERVAL_SECONDS = 300.0


@dataclass(frozen=True)
class ActiveTenant:
    """Who is making this request, and which of their profiles it acts on."""

    tenant_ref: str
    role: TenantRole
    #: The profile this request reads and writes — the scope every facade call
    #: is given.
    workspace_id: str
    #: Every workspace this tenant owns. ``X-Workspace-Id`` is honoured only
    #: when it names one of these.
    workspace_ids: tuple[str, ...]
    is_anonymous: bool


_active: ContextVar[ActiveTenant | None] = ContextVar("active_tenant", default=None)


def set_active_tenant(tenant: ActiveTenant) -> Token[ActiveTenant | None]:
    """Publish the request's tenant; pass the token to :func:`reset_active_tenant`."""
    return _active.set(tenant)


def reset_active_tenant(token: Token[ActiveTenant | None]) -> None:
    """Restore whatever was published before ``token`` was issued."""
    _active.reset(token)


def active_tenant() -> ActiveTenant:
    """The request's tenant.

    Raises ``LookupError`` when called outside a request that went through
    ``TenantMiddleware`` — a bug, not a condition to paper over: silently
    falling back to a default workspace is exactly the cross-tenant read this
    module exists to prevent.
    """
    tenant = _active.get()
    if tenant is None:
        raise LookupError("No active tenant: TenantMiddleware did not run")
    return tenant


def current_workspace_id() -> str | None:
    """The active workspace, or ``None`` outside a request.

    For the synchronous, request-context-free callers (the config cache, the
    API-key lookup): they need to degrade to the instance default rather than
    raise, because they also run from startup migrations and scripts.
    """
    tenant = _active.get()
    return tenant.workspace_id if tenant is not None else None


def active_role() -> TenantRole:
    """The caller's role, defaulting to ``admin`` outside a request.

    Startup migrations and one-off scripts run with no tenant and are the
    operator, so they keep the privileges ``single`` mode always had.
    """
    tenant = _active.get()
    return tenant.role if tenant is not None else "admin"


# -- tenant -> workspaces cache ---------------------------------------------
#
# One process per container (``config_cache`` already assumes this), so a plain
# dict is correct. Invalidated explicitly by every workspace write.
_cache: dict[str, tuple[tuple[str, ...], str]] = {}
_cache_lock = asyncio.Lock()
_touched: dict[str, float] = {}
_touch_lock = threading.Lock()


def invalidate(tenant_ref: str | None = None) -> None:
    """Drop the cached workspace list for one tenant, or for all of them."""
    if tenant_ref is None:
        _cache.clear()
        return
    _cache.pop(tenant_ref, None)


def _due_for_touch(tenant_ref: str, now: float) -> bool:
    """True at most once per :data:`_TOUCH_INTERVAL_SECONDS` per tenant."""
    with _touch_lock:
        last = _touched.get(tenant_ref)
        if last is not None and now - last < _TOUCH_INTERVAL_SECONDS:
            return False
        _touched[tenant_ref] = now
        return True


def _header(scope: Scope, name: str) -> str:
    """One request header, lowercased-name lookup against the raw ASGI list."""
    wanted = name.encode("latin-1")
    for key, value in scope.get("headers", ()):
        if key == wanted:
            return value.decode("latin-1").strip()
    return ""


class TenantMiddleware:
    """Resolve the request's tenant into a ``ContextVar``.

    A **pure ASGI** middleware, not ``BaseHTTPMiddleware``: the latter runs the
    downstream app in a separate task, so a ``ContextVar`` set here would not
    be visible to the endpoint.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path in EXEMPT_PATHS or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        header_mode = settings.tenant_mode == "header"
        if header_mode:
            tenant_ref = _header(scope, TENANT_HEADER)
            if not tenant_ref:
                # Not 401: an instance in header mode is only ever reached
                # through the gateway, so a request without a tenant is not a
                # visitor who forgot to log in — it is someone who bypassed the
                # proxy. Say nothing about what lives here.
                await self._not_found(send)
                return
            role: TenantRole = (
                "admin" if _header(scope, ROLE_HEADER).lower() == "admin" else "anon"
            )
        else:
            tenant_ref, role = SINGLE_TENANT_REF, "admin"

        tenant = await self._resolve(
            tenant_ref, role, requested=_header(scope, WORKSPACE_HEADER)
        )
        if header_mode:
            await self._touch(tenant_ref)

        token = set_active_tenant(tenant)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_active_tenant(token)

    @staticmethod
    async def _not_found(send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"detail":"Not found"}'})

    async def _resolve(
        self, tenant_ref: str, role: TenantRole, *, requested: str
    ) -> ActiveTenant:
        ids, default_id = await self._workspaces(tenant_ref, role)
        # An `X-Workspace-Id` that is not this tenant's degrades to the
        # tenant's own default rather than 404-ing: the header is browser
        # localStorage, which outlives a tenant (a new gateway cookie means a
        # new tenant), and the tenant's own default is always safe.
        workspace_id = requested if requested in ids else default_id
        return ActiveTenant(
            tenant_ref=tenant_ref,
            role=role,
            workspace_id=workspace_id,
            workspace_ids=ids,
            is_anonymous=role == "anon",
        )

    async def _workspaces(
        self, tenant_ref: str, role: TenantRole
    ) -> tuple[tuple[str, ...], str]:
        """This tenant's workspace ids and its default, creating one if needed."""
        cached = _cache.get(tenant_ref)
        if cached is not None:
            return cached
        # Serialize misses so two simultaneous first requests from one tenant
        # cannot each create a workspace.
        async with _cache_lock:
            cached = _cache.get(tenant_ref)
            if cached is not None:
                return cached
            resolved = await self._load(tenant_ref, role)
            _cache[tenant_ref] = resolved
            return resolved

    @staticmethod
    async def _load(
        tenant_ref: str, role: TenantRole
    ) -> tuple[tuple[str, ...], str]:
        from app.database import db

        rows = await db.workspaces_for_tenant(tenant_ref)
        if not rows and role == "admin":
            # First sight of an admin: adopt the data this instance already
            # holds instead of orphaning it. Anonymous requests never claim.
            claimed = await db.claim_unowned_workspaces(tenant_ref)
            if claimed:
                logger.info(
                    "Admin tenant claimed %d pre-existing workspace(s)", claimed
                )
                rows = await db.workspaces_for_tenant(tenant_ref)
        if not rows:
            created = await db.create_workspace(
                name="Default",
                tenant_ref=tenant_ref,
                is_anonymous=role == "anon",
            )
            rows = [created]
            logger.info("Created first workspace for a new tenant (role=%s)", role)

        ids = tuple(str(row["workspace_id"]) for row in rows)
        default_id = next(
            (str(row["workspace_id"]) for row in rows if row.get("is_default")),
            ids[0],
        )
        return ids, default_id

    @staticmethod
    async def _touch(tenant_ref: str) -> None:
        if not _due_for_touch(tenant_ref, time.monotonic()):
            return
        from app.database import db

        try:
            await db.touch_tenant(tenant_ref, datetime.now(timezone.utc).isoformat())
        except Exception:
            # A liveness stamp is not worth failing a request over; the worst
            # case is that an active tenant looks idle to the purge, which the
            # next successful stamp corrects.
            logger.warning("Could not stamp last_seen_at for a tenant", exc_info=True)
