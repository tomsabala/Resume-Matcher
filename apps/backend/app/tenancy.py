"""Request-scoped tenant identity.

One instance of this app can serve many visitors. The identity comes from an
upstream gateway, which authenticates the visitor and injects three headers on
every proxied request:

* ``X-Apps-Tenant`` — an opaque identity ref (the gateway's ``anon-<16 hex>`` /
  ``admin-<16 hex>``, treated here as a plain string).
* ``X-Apps-Role`` — ``admin`` for a whitelisted operator, anything else is
  anonymous.
* ``X-Apps-Proxy-Secret`` — the shared secret proving the request really came
  through the gateway.

**The secret is what makes the other two trustworthy.** Without it the role is
self-asserted: anyone who can put a header on a request that reaches this app
— directly, or through the frontend's ``/api/:path*`` rewrite — is an admin,
which means the operator's ``LLM_API_KEY`` and every unclaimed workspace.
Reachability is not a boundary, so this module does not treat it as one.

Two further rules follow from the same mistrust:

* A repeated identity header is rejected, not resolved. Duplicates mean
  something upstream *appended* its value instead of replacing the client's,
  and picking an occurrence is a guess an attacker chooses.
* In ``single`` mode any identity header at all is rejected. A private
  instance has no gateway, so their presence means either a probe or a
  deployment that turned the gateway on and forgot ``TENANT_MODE=header`` —
  the silent misconfiguration that shares one dataset with every visitor.

``TenantMiddleware`` resolves those headers into an :class:`ActiveTenant` **once
per request**, in the same task that runs the endpoint, and publishes it on a
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
import hmac
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
SECRET_HEADER = "x-apps-proxy-secret"
WORKSPACE_HEADER = "x-workspace-id"

#: The headers that carry identity. Repeating any of them is rejected, and in
#: ``single`` mode presenting any of them at all is rejected.
IDENTITY_HEADERS = (TENANT_HEADER, ROLE_HEADER, SECRET_HEADER)

#: The tenant every row carries in ``single`` mode, and the one an operator
#: transfers to a real tenant ref with ``CLAIM_TENANT_REF`` when an instance is
#: flipped to ``header`` mode.
SINGLE_TENANT_REF = ""

TenantRole = Literal["anon", "admin"]

# Paths that must answer without a tenant: the container healthcheck hits
# /api/v1/health. The docs paths are listed for the private instance that
# serves them; in header mode ``app.main`` builds the app with no docs routes
# at all, so a shared deployment publishes no endpoint inventory.
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


def _header_values(scope: Scope, name: str) -> list[str]:
    """Every value sent for ``name``, lowercased-name lookup against ASGI."""
    wanted = name.encode("latin-1")
    return [
        value.decode("latin-1").strip()
        for key, value in scope.get("headers", ())
        if key == wanted
    ]


def _sole_header(scope: Scope, name: str) -> str | None:
    """The one value sent for ``name``, or ``None`` when it was repeated.

    Returning the first (or last) occurrence of a repeated identity header is
    a guess, and the attacker picks which way it goes: a gateway that appends
    its value instead of replacing the client's leaves both on the wire. There
    is no correct answer, so there is no answer.
    """
    values = _header_values(scope, name)
    if len(values) > 1:
        return None
    return values[0] if values else ""


def _secret_matches(presented: str) -> bool:
    """Constant-time comparison against the configured gateway secret.

    Compared as bytes: ``hmac.compare_digest`` raises ``TypeError`` on a
    non-ASCII ``str``, and the presented value is attacker-controlled — a
    single high byte in the header would turn a 404 into a 500 and say that
    something is listening. ``Settings`` keeps the configured side ASCII, so
    the round trip is lossless for every value that can match.
    """
    expected = settings.gateway_secret
    if not expected:
        return False
    return hmac.compare_digest(
        presented.encode("utf-8", "replace"), expected.encode("utf-8", "replace")
    )


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
        if not header_mode and any(
            _header_values(scope, name) for name in IDENTITY_HEADERS
        ):
            # A private instance has no gateway to have injected these. Either
            # someone is probing, or the gateway is live and TENANT_MODE was
            # never flipped — in which case every visitor is currently sharing
            # the operator's single dataset and must be stopped, loudly.
            logger.error(
                "Rejected a request carrying gateway identity headers while "
                "TENANT_MODE=single. If this instance is behind a gateway, set "
                "TENANT_MODE=header and GATEWAY_SECRET; until then it is NOT "
                "isolating visitors."
            )
            await self._not_found(send)
            return

        if header_mode:
            secret = _sole_header(scope, SECRET_HEADER)
            tenant_ref = _sole_header(scope, TENANT_HEADER)
            presented_role = _sole_header(scope, ROLE_HEADER)
            if secret is None or tenant_ref is None or presented_role is None:
                logger.warning(
                    "Rejected a request with a repeated identity header: an "
                    "upstream proxy is appending headers instead of replacing "
                    "the client's."
                )
                await self._not_found(send)
                return
            # Not 401: an instance in header mode is only ever reached through
            # the gateway, so a request without a valid secret and tenant is
            # not a visitor who forgot to log in — it is someone who bypassed
            # the proxy. Say nothing about what lives here.
            if not _secret_matches(secret) or not tenant_ref:
                await self._not_found(send)
                return
            role: TenantRole = "admin" if presented_role.lower() == "admin" else "anon"
        else:
            tenant_ref, role = SINGLE_TENANT_REF, "admin"

        requested_workspace = _sole_header(scope, WORKSPACE_HEADER)

        tenant = await self._resolve(
            tenant_ref, role, requested=requested_workspace or ""
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
        """This tenant's workspaces, creating an empty first one if it has none.

        A first-seen tenant never adopts data that is already here. Taking
        ownership of the unowned (``tenant_ref = ""``) workspaces an instance
        held before it was flipped to header mode is an operator decision,
        made once at startup through ``CLAIM_TENANT_REF`` — see
        ``app.main.claim_unowned_workspaces_for_operator``. Deciding it from
        an inbound request made the operator's whole dataset the prize in a
        race that ``X-Apps-Role: admin`` entered for free.
        """
        from app.database import db

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
