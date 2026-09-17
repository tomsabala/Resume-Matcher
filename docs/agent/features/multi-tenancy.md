# Multi-tenancy: one instance, many visitors

## Why

Resume-Matcher is deployed behind the `apps.tom-sabala.dev` gateway, which needs two things
that conflict today:

- every anonymous visitor gets a clean slate,
- a whitelisted admin gets a persistent one.

The gateway currently buys this with **one container per visitor session** — 768 MB of RAM
per concurrent visitor, plus a ~6 s cold start each. Making the app itself multi-tenant
replaces that with **one warm container for everybody**: 768 MB flat, no cold start, and the
same guarantee.

The app is already most of the way there. `workspaces` exists, and `resumes`,
`resume_versions`, `jobs` and `applications` all carry `workspace_id` with an index. What is
missing is that a workspace is documented as *a profile, not a tenant*
(`models.py:31-37`), and the code is written accordingly.

## The trade being made, stated once

Isolation moves from **kernel-enforced** (separate container, separate filesystem, separate
SQLite file, separate `.secret_key`) to **application-enforced** (a `WHERE workspace_id = ?`
on every query). One missing predicate is a cross-tenant data leak, where before it was
impossible by construction.

That is the price of not paying per visitor, and it is accepted. It has two consequences that
are not optional:

1. The test suite becomes the boundary. Cross-tenant denial needs a test per table, not a
   convention.
2. Upstream is deliberately single-user, so every merge from `srbhr/Resume-Matcher` has to
   re-verify scoping. Keep the diff concentrated and keep the tripwire test (§6) green.

## 1. Identity comes from the gateway, never from the client

Today `deps.py:10-24` reads `X-Workspace-Id`, and on an unknown or absent value falls back to
`db.default_workspace_id()`. Both halves are wrong for a shared deployment: the header is
client state (localStorage), and the fallback lands every anonymous visitor in the admin's
workspace.

The gateway already computes a per-visitor identity and already **strips** inbound
`X-Apps-*` and `X-Auth-Request-*` headers, so a header it injects itself cannot be forged by a
client. The contract:

| header | value | meaning |
|---|---|---|
| `X-Apps-Tenant` | `anon-<16 hex>` | hash of the gateway session cookie — new cookie, new tenant |
| `X-Apps-Tenant` | `admin-<16 hex>` | hash of the lowercased admin email — stable across browsers |
| `X-Apps-Role` | `anon` \| `admin` | whether oauth2-proxy authenticated the viewer |

Trust rests on reachability: the container publishes no port and lives on an internal Docker
network, so the only path to it is the broker, which sets these headers on every request.

**Work:**

- `deps.py`: resolve the workspace from `X-Apps-Tenant`, creating one on first sight
  (`external_ref` → workspace). Keep `X-Workspace-Id` as the *within-tenant profile* selector
  it already is, validated to belong to the resolved tenant.
- New setting `TENANT_MODE` (`single` | `header`, default `single`). `single` keeps today's
  behaviour so the app still runs standalone and upstream tests still pass; `header` requires
  `X-Apps-Tenant` and **404s rather than falling back** when it is missing. The deployment
  sets `TENANT_MODE=header`.
- `workspaces` gains `external_ref` (unique, nullable), `is_anonymous`, `last_seen_at`.

## 2. Close the 21 unscoped by-id paths

`database.py` has 73 methods; 18 take a workspace. **21 read or write by id with no workspace
predicate**, so a guessed UUID crosses tenants:

```
get_resume, update_resume, claim_resume_processing, finish_resume_processing,
delete_resume, set_master_resume, seed_resume_version, commit_resume_version,
list_resume_versions, get_job, update_job, delete_job, register_preview, claim_preview,
create_tailored_resume, create_improvement, create_manual_application, create_application,
get_application, update_application, delete_application
```

The mechanical cause is `session.get(Model, id)` — a primary-key load that **cannot** carry a
filter. There are 33 of them (`Resume` 11, `Job` 5, `Application` 5, `ResumeVersion` 4,
`TailoringPreview` 3, `ApiKey` 2, `Workspace` 3).

**Work:** every tenant-owned load becomes a scoped select:

```python
row = (await session.execute(
    select(Resume).where(Resume.resume_id == resume_id, Resume.workspace_id == scope)
)).scalar_one_or_none()
```

Make `scope` a required argument on all 21 — not defaulted. A default is how a call site
silently keeps the old behaviour.

## 3. Scope the three global tables

| table | today | change |
|---|---|---|
| `api_keys` | PK is `provider` alone (`models.py:241`) — one visitor's pasted key becomes everyone's key and everyone's spend | composite PK `(workspace_id, provider)` |
| `improvements` | no `workspace_id`; reachable via `request_id` / `tailored_resume_id` | add `workspace_id` + index, scope every query |
| `tailoring_previews` | no `workspace_id`; reachable via `preview_id` and `claim_token` | add `workspace_id` + index, scope every query including the claim path |

The encryption key (`.secret_key` in `data_dir`) stays instance-wide — it protects data at
rest, and per-tenant keys would buy nothing against an attacker who already has the DB.

## 4. Per-tenant settings and budget

`config.json` in `data_dir` holds features, language, prompts and feature-prompts for the
whole instance, and `/api/v1/config/*` exposes 16 endpoints over it — including
`PUT /prompts`, `PUT /features` and `POST /reset`. In a shared instance an anonymous visitor
can currently reconfigure or factory-reset the app for everybody.

**Work:** a `workspace_settings` table (`workspace_id`, `key`, `value` JSON) read through a
"tenant override, else instance default" resolver, so `config.json` keeps working as the
default layer. Every `/config/*` write targets the caller's tenant. `POST /reset` clears the
caller's tenant only.

`ai_budget` / `ai_limits` are per-process constants and caps. With per-tenant keys the spend
is already the visitor's own, but the concurrency caps (`MAX_ITEM_WORKERS`) are now shared
across visitors — worth a per-tenant semaphore so one long tailoring run cannot starve the
instance.

## 5. Thread the tenant through the print route

`pdf.py` launches Chromium against `FRONTEND_BASE_URL/print/resumes/<id>`. Chromium sends no
app headers, and that is precisely why the default-workspace fallback exists
(`models.py:34-36` says so). With `TENANT_MODE=header` and no fallback, PDF export breaks
unless the tenant travels with the render:

1. `pdf.py`: `page.set_extra_http_headers({"X-Apps-Tenant": workspace_external_ref})`.
2. `app/print/resumes/[id]/page.tsx` and `app/print/cover-letter/[id]/page.tsx`: read that
   header from `headers()` and forward it on the `fetch(${API_BASE}/resumes?...)` call
   (currently `page.tsx:82`, unauthenticated and unscoped).
3. The API accepts it through the same `deps.py` resolver — one code path, not a print-only
   bypass.

This is the step most likely to be missed, because it fails only on export, and only in the
deployed configuration. Cover it with an integration test that renders a PDF for tenant B
while tenant A holds a resume with the same id shape.

## 6. Anonymous lifecycle

- Create on first `X-Apps-Tenant` sighting; stamp `last_seen_at` on every request.
- Purge: delete `is_anonymous` workspaces whose `last_seen_at` is older than N days, cascading
  across `resumes`, `resume_versions`, `jobs`, `applications`, `improvements`,
  `tailoring_previews`, `api_keys`, `workspace_settings`. Without this the shared SQLite grows
  forever — the per-container design got this for free when the tmpfs died.
- Run it from the existing startup path plus a periodic task; an admin endpoint to trigger it
  is useful for operating.

**Tripwire test** (this is what survives an upstream merge): assert that
`session.get(` appears zero times for tenant-owned models in `database.py`, and that every
public method taking `*_id` also takes a scope. A grep-style test is crude and exactly right
here — it fails on the next merge that reintroduces an unscoped load.

## 7. Migration

One Alembic revision, following `0002_workspaces.py` (which is the direct precedent: it added
`workspace_id` to three tables and backfilled the default workspace):

1. `workspaces`: add `external_ref` (unique), `is_anonymous`, `last_seen_at`.
2. `improvements`, `tailoring_previews`: add `workspace_id` + index; backfill by joining
   through `resumes` / `jobs`, falling back to the default workspace.
3. `api_keys`: rebuild with PK `(workspace_id, provider)`, backfilling existing rows to the
   default workspace — SQLite needs a table rebuild, which `0002` already demonstrates.
4. `workspace_settings`: create; optionally seed from `config.json` for the default workspace.
5. Mark the existing default workspace `is_anonymous = 0` and give it the admin's
   `external_ref` so today's data becomes the admin tenant rather than orphaned.

## 8. Tests that define the boundary

Per tenant-owned table, with two tenants A and B:

- B reading A's id → 404, for every by-id endpoint.
- B writing A's id → 404, and A's row unchanged afterwards.
- B listing → only B's rows.
- B's `PUT /config/api-keys` → invisible to A; A's LLM calls use A's key.
- B's `POST /config/reset` → A's settings intact.
- Export as B while A holds a same-shaped id → B's content in the PDF.
- `TENANT_MODE=header` with no `X-Apps-Tenant` → 404, **never** the default workspace.
- A forged `X-Workspace-Id` naming A's workspace, sent by B → refused.
- Purge removes an idle anonymous tenant's rows across all tables and leaves the admin's.

## 9. Rollout

1. Land the app change; `TENANT_MODE=single` keeps every existing deployment working.
2. Rebuild the image: `docker build --build-arg NEXT_PUBLIC_BASE_PATH=/a/resume-matcher -t ghcr.io/tomsabala/resume-matcher:apps-mount .`
3. Gateway: set `TENANT_MODE=header` in `gateway/instances/resume-matcher.shared.env`, and
   flip the manifest entry to `"mode": "shared"`. Delete the now-unused
   `resume-matcher.anon.env` / `.admin.env`.
4. The shared instance is volume-backed, so **its data is now worth backing up** — the old
   anonymous tmpfs was disposable by design. Add the volume to a `restic`/`borg` job before
   real use.
5. Watch `MAX_TOTAL_INSTANCES`: it now bounds *apps*, not visitors.

## What stays the container's job

Not everything collapses into the app, and this is worth keeping straight:

- **The gateway session cookie** is still what makes an anonymous visitor's slate fresh: new
  cookie → new `X-Apps-Tenant` → new workspace. The app never sees the cookie.
- **`access: "admin"`** still hides an app entirely from anonymous visitors, before any
  request reaches it.
- **Per-session containers remain the right answer** for any future app that cannot be made
  multi-tenant. `mode: "session"` stays in the manifest for exactly that case.
