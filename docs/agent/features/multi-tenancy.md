# Multi-tenancy: one instance, many visitors

## Why

Resume-Matcher is deployed behind the `apps.tom-sabala.dev` gateway, which needs two things
that a single-user app cannot give it at once:

- every anonymous visitor gets a clean slate,
- a whitelisted admin gets a persistent one.

The gateway used to buy this with **one container per visitor session** — hundreds of MB of
RAM per concurrent visitor, plus a cold start each. The app is now multi-tenant itself, so
**one warm container serves everybody** with the same guarantee.

## The trade being made, stated once

Isolation moved from **kernel-enforced** (separate container, separate filesystem, separate
SQLite file, separate `.secret_key`) to **application-enforced** (a `WHERE workspace_id = ?`
on every query). One missing predicate is a cross-tenant data leak, where before it was
impossible by construction.

That is the price of not paying per visitor, and it is accepted. It has two consequences that
are not optional:

1. The test suite is the boundary. `tests/integration/test_tenancy.py` denies cross-tenant
   access per table; `tests/unit/test_database_scoping.py` is the structural tripwire.
2. Upstream is deliberately single-user, so every merge from `srbhr/Resume-Matcher` has to
   re-verify scoping. Keep the tripwire green.

## 1. Identity comes from the gateway, never from the client

`TenantMiddleware` (`app/tenancy.py`) resolves the request's identity once, before anything
touches the database, and publishes it on a `ContextVar`. Resolving it in ASGI middleware
rather than a FastAPI dependency is what lets the request-context-free paths see it too: the
synchronous config cache and the API-key lookup are reached through
`get_llm_config` → `load_config_file`, which take no `Request`.

The gateway strips inbound `X-Apps-*` and `X-Auth-Request-*` headers and injects its own, so
a header it sets cannot be forged by a client. The contract:

| header | value | meaning |
|---|---|---|
| `X-Apps-Tenant` | `anon-<16 hex>` | hash of the gateway session cookie — new cookie, new tenant |
| `X-Apps-Tenant` | `admin-<16 hex>` | hash of the lowercased admin email — stable across browsers |
| `X-Apps-Role` | `anon` \| `admin` | whether oauth2-proxy authenticated the viewer |

Trust rests on reachability: the container publishes no port and lives on an internal Docker
network, so the only path to it is the broker, which sets these headers on every request. The
app treats `tenant_ref` as an opaque string and derives anonymity from `X-Apps-Role`, not from
the prefix, so a format change upstream is harmless.

`TENANT_MODE` (`single` | `header`, default `single`) selects the behaviour:

- **`single`** is exactly today's standalone app: one implicit tenant (`tenant_ref = ""`),
  `admin` role, the `LLM_API_KEY` env fallback allowed. The upstream test suite passes
  unchanged.
- **`header`** requires `X-Apps-Tenant` on every `/api/**` request and answers **404**
  without one — never a fallback to the default workspace. The effective mode is logged once
  at startup, because a typo in the instance env file would otherwise degrade silently to
  single-tenant, which is indistinguishable from working until two visitors see each other's
  resumes.

Exempt paths: `/`, `/docs`, `/redoc`, `/openapi.json`, `/api/v1/health`. `GET /status` is
**not** exempt — it reports the caller's own resume counts.

### Tenant → workspaces is one-to-many

`workspaces` gained `tenant_ref` (NOT NULL, `""` = the standalone tenant), `is_anonymous` and
`last_seen_at`. Scoping everywhere is still `workspace_id` alone — no second predicate was
added to the document tables — so the existing multi-profile feature survives per tenant.

`tenant_ref` is NOT NULL with an empty-string sentinel on purpose: the partial unique index
`ux_workspaces_tenant_default` enforces one default workspace per tenant, and SQLite treats
NULLs as distinct, so a nullable column would silently lose that guarantee.

Two deliberate asymmetries:

- **A missing `X-Apps-Tenant` in header mode is a 404**, for every `/api/**` path outside the
  exemptions. An instance in header mode is only reachable through the gateway, so a request
  without a tenant is not a visitor who forgot to log in — it is someone who bypassed the
  proxy.
- **An `X-Workspace-Id` that does not belong to the resolved tenant silently degrades to that
  tenant's own default**, rather than 404-ing. That header is browser localStorage, which
  outlives a tenant (a new gateway cookie means a new tenant), and the tenant's own default is
  always safe.

### The first admin request claims the pre-existing data

A standalone instance flipped to header mode already holds resumes, all carrying
`tenant_ref = ""`. The first `admin`-role request stamps every still-unowned workspace with
that admin's `tenant_ref` (`db.claim_unowned_workspaces`). Anonymous requests never claim.
This is how today's data becomes the admin tenant instead of being orphaned behind a tenant
nobody can present.

If a second admin email is ever whitelisted they get a fresh empty tenant. That is the
intended outcome, not a bug.

## 2. The facade cannot be called unscoped

`app/database.py` is the only layer that can reach a document row, so it is the only place a
cross-tenant read can be introduced. Two mechanical rules now hold, and a test enforces both.

**Rule A — no `session.get` on a tenant-owned model.** A primary-key load cannot carry a
filter. Every one became a scoped select:

```python
row = (await session.execute(
    select(Resume).where(Resume.resume_id == resume_id, Resume.workspace_id == workspace_id)
)).scalar_one_or_none()
```

**Rule B — every `select`/`update`/`delete` on a tenant-owned model carries a `workspace_id`
predicate.** Rule B exists separately because `claim_resume_processing` and
`finish_resume_processing` are bare `update()` statements with no load at all.

The seven tenant-owned models are `Resume`, `ResumeVersion`, `Job`, `Application`,
`TailoringPreview`, `Improvement`, `ApiKey`. `Workspace` is exempt — it *is* the tenant table.
`WorkspaceSetting` is exempt because `workspace_id` is half its primary key.

### Scope is a required argument, never a default

**41 facade methods** now require `workspace_id`. It is **keyword-only** wherever the method
has other positional arguments, so a call site can never silently swap two id strings; a
missing scope is a `TypeError` at the call site, not a silent cross-tenant read.

Three fallbacks were deleted outright, because each one was a way for a call site to keep the
old behaviour:

- `deps.resolve_workspace_id` no longer reads `X-Workspace-Id` — it is a pure read of the
  ContextVar the middleware set.
- `Database._resolve_workspace_id` (`workspace_id or default_workspace_id()`) is gone, and the
  eight methods that used it take a required scope. It sat *below* `deps.py`, so closing only
  the dependency would have left it open.
- `Database.reset_database` is replaced by `reset_workspace(workspace_id)`.

`db.default_workspace_id()` survives, but only as the **instance** default — the standalone
tenant's workspace, for the paths that run outside a request (the legacy key migration, the
TinyDB import, the synchronous config reader). It is deliberately not a request fallback.

### Bugs this closed on the way

Several pre-existing bugs were data-retention leaks waiting for the anonymous purge to ship:

- `delete_resume` never deleted the resume's `resume_versions` rows, so a user who deleted a
  resume kept a full copy of every document version.
- `delete_workspace` never deleted `resume_versions` or `workspace_settings`.
- `replace_api_keys` and `clear_api_keys` issued `delete(ApiKey)` with no `WHERE`, so any
  tenant's settings save wiped every tenant's keys.
- `get_stats` counted every row in the database.
- `register_preview`'s expired-preview GC swept every tenant's rows on any tenant's request.
- The TinyDB import stamped no workspace at all, so imported rows landed in workspace `""`,
  which no request can resolve to.

## 3. The three formerly global tables

| table | before | now |
|---|---|---|
| `api_keys` | PK `provider` alone — one visitor's pasted key became everyone's key and everyone's spend | PK `(workspace_id, provider)` |
| `improvements` | no `workspace_id`; reachable by `request_id` / `tailored_resume_id` | `workspace_id` + `ix_improvements_workspace`, every query scoped |
| `tailoring_previews` | no `workspace_id`; reachable by `preview_id` | `workspace_id` + `ix_previews_workspace`, every query scoped including the claim path |

`uq_application_job_resume` is left **globally** unique and `applications` is not rebuilt: ids
are uuid4, and `create_application` now validates both `job_id` and `resume_id` against the
caller's scope before the dedup select runs, so the constraint can only ever be hit within one
workspace. Both `create_application` and `create_manual_application` raise
`ResumeNotFoundError` / `JobNotFoundError` for an id outside the scope, which the routers map
to 404.

The encryption key (`.secret_key` in `data_dir`) stays instance-wide — it protects data at
rest, and per-tenant keys would buy nothing against an attacker who already has the database.

## 4. Per-tenant settings, keys and LLM routing

`config.json` is now the **instance default** layer only. A tenant's own choices live in
`workspace_settings` (`workspace_id`, `key`, `value` JSON) and are merged over it, key by key:
"tenant override, else instance default". `config.json` is written only by the operator out of
band and by the two startup migrations.

The overridable keys are a flat allowlist in `app/config_cache.py`
(`OVERRIDABLE_CONFIG_KEYS`): `provider`, `model`, `api_base`, `reasoning_effort`, the three
`enable_*` feature toggles, `ui_language`, `content_language`, `language`,
`default_prompt_id`, `cover_letter_prompt`, `outreach_message_prompt`. Everything else in the
file stays instance-wide.

Both readers produce the same merged view, or `GET /config` would disagree with what the LLM
path actually uses:

- `config_cache.load_config()` — re-keyed from `path` to `(path, workspace_id)`, same 300 s
  TTL, same `copy.deepcopy` return. `invalidate_config_cache(workspace_id=None)` clears one
  tenant or all of them.
- `config.load_config_file(workspace_id=None)` — the same merge, plus the workspace's
  decrypted `api_keys`. It resolves its own scope when not given one.

Every one of the 16 `/api/v1/config/*` endpoints takes the caller's workspace. Writes go to
that workspace's override rows via `_save_overrides`, which writes **only its own endpoint's
key group** — saving the feature toggles must not freeze that tenant's provider and model as
overrides too. `POST /config/reset` calls `reset_workspace`, which truncates the caller's
documents and deliberately preserves their API keys and setting overrides.

**The env key fallback is gated.** `resolve_api_key(stored, provider, *, allow_env_fallback)`
applies `settings.llm_api_key` only when `tenant_mode == "single"` or the caller's role is
`admin` (which is also what a request-less script reports). Without this, every anonymous
visitor would silently spend the operator's `LLM_API_KEY`. An anonymous visitor with no key of
their own gets the existing "no API key configured" error.

**The router cache is bounded.** `get_router` memoizes one LiteLLM `Router` per config
fingerprint in an `OrderedDict` of at most 8 entries, LRU-evicted. A single global slot would
be rebuilt on every request as two tenants with different providers alternated.

**The gpt-5 `reasoning_effort` migration only persists in single mode.** `stored` is a merged
view, so writing it back on a shared instance would flatten one tenant's provider and model
into the instance-wide `config.json`. The in-memory value still applies, so the behaviour the
migration preserves is identical either way.

`ai_events` records are per workspace too — without the filter, tenant B could read tenant A's
provider error text, which can contain prompt fragments. The deque's `maxlen` stays global, so
a noisy tenant can evict another's diagnostics; that is acceptable for a best-effort panel.

## 5. The tenant travels into the Chromium render

Chromium fetches the Next print route over loopback, bypassing the gateway, so it carries no
`X-Apps-*` of its own. This is the step that fails only in the deployed configuration and only
on export.

1. `pdf.py`'s `render_resume_pdf(..., headers=...)` threads the headers through both render
   paths — the shared browser *and* the threaded fallback — to
   `page.set_extra_http_headers(...)` immediately before `page.goto`. Per **page**, not per
   browser context: the browser is process-wide and shared across tenants and up to
   `_PDF_MAX_CONCURRENCY` concurrent renders, so context-level headers would leak one caller's
   identity into another's export.
2. `download_resume_pdf` and `download_cover_letter_pdf` send `X-Workspace-Id` plus
   `X-Apps-Tenant` when there is one. Both are needed: the workspace id selects the right
   *profile*, the tenant ref the right tenant.
3. `app/print/resumes/[id]/page.tsx` and `app/print/cover-letter/[id]/page.tsx` read those
   headers from `next/headers` and forward them on their outbound `fetch`. They are server
   components using bare `fetch`, so they never pass through the header injector in
   `lib/api/client.ts`.

The tenant ref stays out of render error messages — it is a cookie hash.

`FRONTEND_BASE_URL` needs no change for the mount prefix: the broker injects
`FRONTEND_BASE_URL=http://127.0.0.1:<port>/a/<slug>` per instance, and
`resolveRuntimeApiBase` already strips that prefix for the print route's server-side fetch
back to uvicorn.

## 6. Anonymous lifecycle

- A workspace is created on first sight of a tenant, `is_anonymous` set from the role.
- `last_seen_at` is stamped per request, throttled to at most once per 300 s per tenant by an
  in-process dict. A write per request would be pure WAL amplification when the purge
  threshold is hours.
- `db.purge_idle_anonymous(idle_before)` deletes every `is_anonymous` workspace not seen since
  the cutoff, and its rows from `tailoring_previews`, `improvements`, `applications`,
  `resume_versions`, `resumes`, `jobs`, `api_keys` and `workspace_settings`. **There are no
  foreign keys anywhere in this schema**, so nothing cascades — all nine deletes are explicit,
  children before parents, in one write transaction. Per-table counts are logged at INFO.
- It runs from the lifespan: once at startup, then hourly, cancelled on shutdown. Skipped
  entirely in `single` mode. `ANONYMOUS_RETENTION_HOURS` defaults to 24, bounded to
  `[1, 8760]`, so the deployment can change it without a rebuild.

There is deliberately **no admin endpoint** to trigger a purge: that would be a new auth
surface for no gain.

## 7. Migration `0006_tenancy`

1. `workspaces`: add `tenant_ref` (server default `""`), `is_anonymous`, `last_seen_at`;
   backfill `last_seen_at`; create `ix_workspaces_tenant`; swap
   `ux_workspaces_single_default` → `ux_workspaces_tenant_default`.
2. `improvements`: add `workspace_id` + index, backfill by `COALESCE` through
   `original_resume_id` → `tailored_resume_id` → `job_id` → the default workspace.
3. `tailoring_previews`: the same shape through `source_id` → `result_resume_id` → `job_id`.
4. `api_keys`: rebuilt in batch mode with PK `(workspace_id, provider)`, existing rows
   stamped with the default workspace.
5. `workspace_settings`: created, and deliberately **not** seeded from `config.json` — an
   empty override table means "instance default", which is exactly right for the pre-existing
   tenant.

Two caveats, both in the revision's own docstring:

- **Historical orphans fall back to the default workspace.** `delete_resume` and `delete_job`
  have always removed parent rows without touching `improvements` or `tailoring_previews`, so
  rows whose resume and job are both gone exist and cannot be joined to a workspace. They are
  inert history, so they are stamped rather than deleted.
- **The downgrade is lossy for API keys.** A single-column `provider` key cannot hold two
  tenants' keys, so every non-default workspace's are dropped first. Downgrading also drops
  every per-tenant override.

The `api_keys` rebuild passes `copy_from` explicitly. Batch-mode reflection of the unnamed
`PrimaryKeyConstraint("provider")` would otherwise carry the old single-column key into the
rebuilt table — `alembic check` does not diff primary keys, so nothing else would notice.

`db_engine._create_at_head` builds fresh databases with `create_all` + a hand-written
`alembic_version` stamp, so no other test replays a migration. `0002_workspaces.py` is the
precedent for the column adds and the index swap, but note it contains **no table rebuild**.

## 8. Tests that define the boundary

| file | what it pins |
|---|---|
| `tests/integration/test_tenancy.py` | Cross-tenant denial, per table: B reading A's id → 404; B writing A's id → 404 and A's row byte-identical; B's list → only B's rows. Plus: no tenant in header mode → 404 while `/health` still answers; the first admin request claims the pre-existing data and an anonymous one never does; a foreign `X-Workspace-Id` degrades to the caller's own default; per-tenant keys, prompts, features and reset; another tenant's workspace cannot be renamed or deleted; a tenant keeps multiple profiles. |
| `tests/unit/test_database_scoping.py` | The structural tripwire. Parses `database.py` with `ast` and asserts Rules A and B for the seven tenant-owned models, with no allowlist. A third test proves the rules still fire, so a refactor cannot leave two tests that pass against anything. |
| `tests/integration/test_migration_0006.py` | The only test that replays migrations: both backfills including the orphan fallback, the per-tenant default index, the composite `api_keys` key (two tenants may hold the same provider; the same pair twice may not), and a full downgrade/upgrade round trip. |
| `tests/integration/test_pdf_tenancy.py` | The export forwards the caller's workspace, and the tenant ref too in header mode, on both the shared-browser and threaded-fallback paths; another tenant's export 404s before Chromium is asked to render; the tenant ref stays out of the error text. |

The per-test isolation fixture clears the tenancy cache and the `last_seen_at` throttle, both
process-global by design — without that, one test resolves the previous test's workspace.

## 9. Operating notes

- **One uvicorn worker per container.** Already assumed by `config_cache`, and now also by the
  tenancy cache and the `last_seen_at` throttle. If the deployment ever scales to multiple
  workers, the caches go stale per worker; at that point move the tenancy lookup to a
  per-request query and drop the dict, rather than inventing cross-process invalidation.
- **No websocket or SSE surface exists in this app**, so the gateway's untenanted-upgrade hole
  is not reachable here. Do not build for it.
- **`uploads/` is dead.** Nothing under `app/` wrote it; its only reference was the
  `shutil.rmtree` inside the old `reset_database`, and it went with that method.
- **The shared volume is now worth backing up.** The old anonymous tmpfs was disposable by
  design; a shared SQLite holding every visitor's work is not. The socket-proxy sets
  `VOLUMES: 0`, so this is a host-side job, not something the broker can do.

## Gateway-side steps (out of scope for this repo)

1. Merge and deploy the gateway branch that injects `X-Apps-Tenant` — header *stripping* is on
   `main`, injection is not. Nothing here works until that lands.
2. `frontend/src/apps/apps.json`: `"mode": "shared"` for `resume-matcher`, and re-size
   `memoryMb` — shared mode puts every tenant's export in one cgroup with swap disabled, so an
   OOM kill now takes all tenants down at once. `dataTmpfsMb` becomes dead weight.
3. Create `gateway/instances/resume-matcher.shared.env` on the VPS with `TENANT_MODE=header`.
   A missing env file is only a `log.warn`, which is why the app logs its effective mode at
   startup.
4. Rebuild with **both** build args:
   `docker build --build-arg NEXT_PUBLIC_BASE_PATH=/a/resume-matcher --build-arg NEXT_PUBLIC_API_URL=/ -t ghcr.io/tomsabala/resume-matcher:apps-mount .`
5. Retract the operator documentation that says Resume-Matcher must not run shared.
6. Back up the `apps-resume-matcher-shared` volume before real use.
7. Prune the old `apps-resume-matcher-anon-*` / `-admin-*` containers and volumes: after the
   flip they are referenced by no key and will never be reaped by name.

## What stays the container's job

Not everything collapses into the app, and this is worth keeping straight:

- **The gateway session cookie** is still what makes an anonymous visitor's slate fresh: new
  cookie → new `X-Apps-Tenant` → new workspace. The app never sees the cookie.
- **`access: "admin"`** still hides an app entirely from anonymous visitors, before any
  request reaches it.
- **Per-session containers remain the right answer** for any future app that cannot be made
  multi-tenant. `mode: "session"` stays in the manifest for exactly that case.
