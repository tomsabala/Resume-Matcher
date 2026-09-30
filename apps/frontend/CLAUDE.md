# CLAUDE.md - Frontend (apps/frontend)

> Frontend deep-dive for Claude Code. Read the repo-root [`.claude/CLAUDE.md`](../../.claude/CLAUDE.md) and [`docs/agent/README.md`](../../docs/agent/README.md) first for project-wide context. This file goes deeper on the Next.js app only.

**Stack:** Next.js 16 (App Router, Turbopack) · React 19 · TypeScript (strict) · Tailwind CSS v4 · no UI framework (hand-rolled `components/ui`). Import alias `@/*` → `apps/frontend/*`.

---

## Route / Page Map

App Router under `app/`. A `(default)` route group wraps the main app in providers; `print/*` is provider-free (server-rendered for headless-Chromium PDF capture).

| Route                      | File                                   | Type                                                     | Purpose                                                                                             |
| -------------------------- | -------------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `/`                        | `app/(default)/page.tsx`               | Server                                                   | Redirects to `/dashboard`                                                                           |
| `/dashboard`               | `app/(default)/dashboard/page.tsx`     | Client                                                   | Resume list, upload, delete, retry, status grid                                                     |
| `/builder`                 | `app/(default)/builder/page.tsx`       | Client wrapper → `components/builder/resume-builder.tsx` | Master-resume editor (forms, drag-drop sections, templates, AI regenerate, cover letter / outreach) |
| `/tailor`                  | `app/(default)/tailor/page.tsx`        | Client                                                   | Paste JD → preview/confirm tailored resume (diff modal, per-row accept)                             |
| `/tracker`                 | `app/(default)/tracker/page.tsx`       | Client                                                   | Kanban application tracker — 7-column board (drag/drop, bulk ops, manual add)                       |
| `/resume-wizard`           | `app/(default)/resume-wizard/page.tsx` | Client                                                   | AI-led wizard that builds a master resume one question at a time                                    |
| `/settings`                | `app/(default)/settings/page.tsx`      | Client                                                   | LLM provider/model/key, per-provider API keys, features, prompts, reset DB                          |
| `/resumes/[id]`            | `app/(default)/resumes/[id]/page.tsx`  | Client                                                   | View one resume, download PDF, rename, enrichment modal                                             |
| `/compare`                 | `app/(default)/compare/page.tsx`       | Client                                                   | Structured diff of two documents — `?base=&head=` with `resume:<id>` / `version:<id>` tokens        |
| `/print/resumes/[id]`      | `app/print/resumes/[id]/page.tsx`      | **Server**                                               | Print-only resume render for PDF (reads `searchParams` for template settings)                       |
| `/print/cover-letter/[id]` | `app/print/cover-letter/[id]/page.tsx` | **Server**                                               | Print-only cover-letter render for PDF                                                              |

`app/layout.tsx` (root) wires fonts (Geist + Space Grotesk + Noto Sans SC/JP/KR) and global CSS. `app/(default)/layout.tsx` nests providers: `StatusCacheProvider` → `WorkspaceProvider` → `ResumePreviewProvider` → `LocalizedErrorBoundary`, then `AppHeader` + `main`.

> Most pages are `'use client'`. The `print/*` pages are intentionally server components and fetch from the backend directly via `API_BASE` + `lib/i18n/server.ts` (`translate`). Do not add `'use client'` to them.

---

## Directory Layout

```
app/                 # routes (see table)
components/
  ui/                # primitives: button, input, textarea, dialog, dropdown,
                     #   card, retro-tabs, toggle-switch, confirm-dialog,
                     #   rich-text-editor (Tiptap), link-dialog, label
  builder/           # builder page UI + forms/ (one editor per SectionKind)
  resume/            # resume render templates + section-kinds/ (one renderer
                     #   per SectionKind) + styles/*.module.css
  resume-wizard/     # AI-led one-question-at-a-time master-resume wizard
  dashboard/         # resume list/card, upload dialog
  diff/              # the one diff UI: diff-view (DiffView/DiffRows),
                     #   diff-row-line, diff-section-group, diff-stats-bar,
                     #   paths.ts (which rows are individually acceptable)
  tailor/            # diff-preview-modal
  tracker/           # kanban-board, kanban-column, application-card,
                     #   card-detail-modal, bulk-action-bar,
                     #   manual-add-application-dialog, reorder.ts (pure planMove)
  enrichment/        # AI enrichment wizard modal/steps
  versions/          # resume version history
  preview/           # paginated A4/Letter preview (use-pagination.ts)
  home/              # swiss-grid
  settings/          # api-key-menu
  common/            # app-header, workspace-switcher, error-boundary,
                     #   resume_previewer_context
lib/
  api/               # backend client (see Data Flow)
  i18n/              # translation engine (see "UI copy")
  context/           # status-cache, workspace-context
  utils/             # section-helpers, resume-normalization, resume-content,
                     #   keyword-matcher, download, html-sanitizer,
                     #   *-draft-storage, preview-error, tracker-column-visibility
  types/             # document.ts (THE resume contract), template-settings, lucide.d.ts
  config/version.ts  # APP_VERSION / codename
  constants/page-dimensions.ts
hooks/               # use-file-upload, use-regenerate-wizard, use-enrichment-wizard,
                     #   use-operation-owner
messages/en.json     # the sole UI copy bundle
tests/               # vitest (see Testing)
```

---

## Data Flow (page → hook → lib/api → backend)

All backend calls go through **`lib/api/`** — never call `fetch` to the backend directly from a component.

- `lib/api/client.ts` — single source of truth. Exports `apiFetch / apiPost / apiPatch / apiPut / apiDelete`, `API_URL`, `API_BASE`, `getUploadUrl()`, `setActiveWorkspaceId()`.
  - Every request carries `X-Workspace-Id` from a module-level slot that `WorkspaceProvider` owns; unset (or unknown) means the backend's default workspace.
  - Base URL: `NEXT_PUBLIC_API_URL` (default `'/'`) → `API_BASE` becomes `/api/v1`. On the **server** a `/`-relative base is rewritten to `http://127.0.0.1:8000/api/v1` (`INTERNAL_API_ORIGIN`); browser uses the relative path (proxied by `next.config.ts` rewrites to `BACKEND_ORIGIN`).
  - Default request timeout **240_000ms** (matches backend `wait_for` hard limit). `AbortError` → friendly "Request timed out" message.
- `lib/api/resume.ts` — resumes/jobs: upload, improve / improve.preview / improve.confirm, fetch, list, update (PATCH), PDF URLs + blob download, delete, cover-letter / outreach generate+update, rename, retry-processing, fetch JD.
- `lib/api/config.ts` — LLM config, `testLlmConnection`, system `/status`, feature flags, prompt config, **feature prompts** (`FeaturePromptsError` for 422 `missing_placeholders`), **per-provider API-key management** (each provider's key persists independently — switching the active provider no longer wipes another's; stored encrypted server-side), `resetDatabase`. `PROVIDER_INFO` lists supported providers + default models.
- `lib/api/enrichment.ts` — AI enrichment (analyze/enhance/apply) and AI regenerate (regenerate/apply-regenerated).
- `lib/api/diff.ts` — `compareDocuments` / `compareTexSources` over `POST /diff`, the `DocumentDiff` / `DiffRow` types every diff surface renders, and the `resume:<id>` / `version:<id>` ref-token helpers the `/compare` URL uses.
- `lib/api/tracker.ts` — application-tracker CRUD/bulk over `apiFetch/apiPost/apiPatch/apiDelete`: grouped list, detail (JD + resume), manual add, status/position/notes PATCH, bulk move, delete, bulk-delete.
- `lib/api/workspaces.ts` — workspace list/create/update/delete. A workspace scopes resumes, jobs and tracker cards.
- `lib/api/index.ts` — barrel re-export (note: not everything is re-exported; some functions are imported from `./resume` / `./config` / `./enrichment` directly).

**Contracts:** `lib/api/*` interfaces mirror backend Pydantic schemas. See [front-end-apis.md](../../docs/agent/apis/front-end-apis.md) and [api-flow-maps.md](../../docs/agent/apis/api-flow-maps.md).

**Shared client state (React Context, not a fetch lib):**

- `StatusCacheProvider` (`lib/context/status-cache.tsx`) — caches `/status` (LLM health 30min, DB stats 5min stale), with optimistic counter updates. Use `useStatusCache()` / `useIsStatusStale()`.
- `WorkspaceProvider` (`lib/context/workspace-context.tsx`) — active workspace in `localStorage['rm.activeWorkspaceId']`, seeded into the API client on first render so the first fetch after a reload is already scoped. Use `useWorkspace()`; depend on its `revision` to refetch page data after a switch. Switching also drops workspace-bound local ids (`master_resume_id`, `resume_builder_draft`). The switcher is `components/common/workspace-switcher.tsx`, mounted by `components/common/app-header.tsx`.

> The **tracker board owns its state locally** — `components/tracker/kanban-board.tsx` holds the columns in `useState` and owns the single `@dnd-kit` `DndContext`. There is **no** `TrackerProvider` / tracker context; don't look for one.

---

## The Resume Document — READ THIS BEFORE TOUCHING RESUME UI

`lib/types/document.ts` is the **single** home for resume shape types. Import
from there; never redeclare a resume type in a component. It mirrors
`apps/backend/app/schemas/document.py`.

```ts
ResumeDocument { schemaVersion: 2; header: Header; sections: Section[] }
Section { id, key, heading, headingI18nKey?, kind, visible, column, text, entries, tags, groups }
SectionKind = 'text' | 'entries' | 'tags' | 'groups'
Entry { id, title, subtitle, meta, period, links, summary, bullets }
Bullet { text, style: 'bullet' | 'plain' }
```

Sections are **data**: order is `doc.sections` order, the heading is free text,
the shape is `section.kind`, and `column` (`'main' | 'side'`) is how two-column
templates partition. The header is not a section. **No component enumerates
resume sections** — a section the user just invented must render and edit with
no code change.

### Two registries, and only two

| Concern | Registry                 | File                                       |
| ------- | ------------------------ | ------------------------------------------ |
| Render  | `SECTION_KIND_RENDERERS` | `components/resume/section-kinds/index.ts` |
| Edit    | `SECTION_KIND_FORMS`     | `components/builder/forms/index.ts`        |

Both are `Record<SectionKind, React.FC<…>>`, so they are exhaustive by
construction: adding a kind to the contract keeps the build red until a
renderer **and** a form exist for it. Templates call `SectionBlock`, which does
the renderer lookup; `resume-form.tsx` does the form lookup. Never branch on a
section's key or heading — dispatch on `kind`.

Helpers (`lib/utils/section-helpers.ts`) are exactly four: `visibleSections`,
`allSections`, `createSection`, `sectionHeading`.

### The `sectionHeading` i18n rule

Sections projected from the v1 built-ins carry `headingI18nKey` (e.g.
`resume.sections.experience`); user-created sections carry `null`.

> Render `t(section.headingI18nKey)` **only while `section.heading` still
> equals that key's English default.** Once the user edits the heading, the
> literal text wins.

`sectionHeading(section, t)` is the single implementation — use it, don't
re-derive it. **Never pass a user-authored heading to `t()`:** `Messages =
typeof en` makes an unknown key a build failure, and `getNestedValue` would
echo the dot-path back to the user as their section title.

Templates receive headings already resolved (the caller maps sections through
`sectionHeading` first) and render `section.heading` verbatim.

See [custom-sections.md](../../docs/agent/features/custom-sections.md) and
[adding-resume-templates.md](../../docs/agent/features/adding-resume-templates.md).

---

## UI copy — English only

There is no locale system: the app ships one bundle, `messages/en.json`, and no
language setting. `i18n/config.ts` keeps `locales = ['en']` and `defaultLocale`
so the types stay honest.

Engine (no external i18n lib, plain JSON):

- `lib/i18n/messages.ts` — static-imports `en.json`; `type Messages = typeof en`.
- `lib/i18n/translations.ts` — `useTranslations()` returns `{ t, messages, locale: 'en' }`;
  `t('a.b.c', params)` does dot-path lookup + `{placeholder}` substitution. A missing key
  returns the key string (no throw). Components still destructure `locale` in places; it is
  always `'en'`.
- `lib/i18n/server.ts` — `translate('en', key, params)` for the server/print pages.

Date and number formatting uses the `'en-US'` literal at each call site, not a variable.

The three Noto Sans CJK webfaces in `app/layout.tsx` and the `CJK_VARS` fallback in
`lib/types/template-settings.ts` are **not** an i18n feature: they exist so an _uploaded_
resume carrying a non-Latin name or employer renders as glyphs instead of tofu. Leave them.

---

## Styling — Swiss International Style (MANDATORY)

All UI changes MUST follow the Swiss design system. Pack: [README](../../docs/portable/swiss-design-system/README.md) · [tokens](../../docs/portable/swiss-design-system/tokens.md) · [components](../../docs/portable/swiss-design-system/components.md) · [anti-patterns](../../docs/portable/swiss-design-system/anti-patterns.md) · [layouts](../../docs/portable/swiss-design-system/layouts.md).

Tailwind v4, configured **in CSS** (`app/(default)/css/globals.css`, `@theme inline`) — there is no `tailwind.config`. PostCSS uses `@tailwindcss/postcss`. Light theme only.

| Token                      | Value                                          | Tailwind                           |
| -------------------------- | ---------------------------------------------- | ---------------------------------- |
| Canvas / background        | `#F0F0E8`                                      | `bg-background`, `bg-canvas`       |
| Ink (text)                 | `#000000`                                      | `text-ink`, `text-ink-soft`        |
| Hyper Blue (primary/links) | `#1D4ED8`                                      | `text-primary`, `bg-primary`, ring |
| Signal Green (success)     | `#15803D`                                      | `text-success`                     |
| Alert Orange (warning)     | `#F97316`                                      | `text-warning`                     |
| Alert Red (error)          | `#DC2626`                                      | `text-destructive`                 |
| Neutrals                   | `paper-tint`, `steel-grey`, `ink-soft` (OKLCH) | use these, not ad-hoc grays        |

Conventions: `rounded-none` everywhere (no radius tokens exist — square corners are intentional). 1px black borders (`border border-black`). **Hard offset shadows** `shadow-sw-xs … shadow-sw-xl` (solid ink, no blur). Fonts: serif headers / `font-sans` (Geist) body / `font-mono` (Space Grotesk) metadata.

Resume render templates have their own CSS modules in `components/resume/styles/`: `_tokens.css` + `_base.module.css` (shared) and one per template (`swiss-single`, `swiss-two-column`, `modern`, `modern-two-column`, `latex`, `clean`, `vivid`), plus `section-kinds.module.css` for the shared per-kind renderers. Template types/settings: `lib/types/template-settings.ts`. See [resume-templates.md](../../docs/agent/features/resume-templates.md), [template-system.md](../../docs/agent/design/template-system.md), [pdf-template-guide.md](../../docs/agent/design/pdf-template-guide.md), [adding-resume-templates.md](../../docs/agent/features/adding-resume-templates.md).

---

## Essential Commands

```bash
# from apps/frontend
npm install
npm run dev       # next dev --turbopack (:3030)
npm run build     # next build  (runs tsc)
npm run start
npm run lint      # eslint .
npm run format    # prettier --write .
npm run test      # vitest run
```

Backend must run separately on :8000 (see root CLAUDE.md). Frontend proxies `/api/*`, `/docs`, `/redoc`, `/openapi.json` to `BACKEND_ORIGIN` via `next.config.ts` rewrites. **Do not create `app/api/` routes** — filesystem routes shadow the proxy.

---

## Non-Negotiable Frontend Rules

1. All UI MUST follow Swiss International Style (links above). `rounded-none`, 1px black borders, hard shadows, brand tokens.
2. Run `npm run lint` and `npm run format` before committing frontend changes.
3. `messages/en.json` is the only copy bundle — the app is English-only; do not reintroduce per-locale files.
4. **Textarea Enter-key pattern** — confirmed in code (e.g. `app/(default)/tailor/page.tsx`): when a textarea sits inside a dialog/form that submits on Enter, stop propagation:
   ```tsx
   const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
     if (e.key === 'Enter') e.stopPropagation();
   };
   ```
5. All backend access via `lib/api/*` (never raw `fetch` to the backend in components).
6. Sanitize user/LLM HTML with `sanitizeHtml` (`lib/utils/html-sanitizer.ts`, DOMPurify, whitelist `strong/em/u/a`) before `dangerouslySetInnerHTML`.
7. Next.js perf patterns are required reading: [nextjs-performance pack](../../docs/portable/nextjs-performance/README.md) + [checklist](../../docs/portable/nextjs-performance/checklist.md).

---

## Key Gotchas

- **Lucide imports:** hot-path/page code imports icons from the deep path (`lucide-react/dist/esm/icons/x`) to avoid the barrel; `optimizePackageImports` in `next.config.ts` also tree-shakes lucide/tiptap/dnd-kit. Stay consistent.
- **240s timeout** on AI calls (`apiFetch` default) — matches backend; don't shorten for improve/regenerate flows.
- **`print/*` pages are server components** that read template settings from `searchParams` and call the backend via internal origin — keep them server-side.
- ESLint disables `react-hooks/set-state-in-effect` (existing effects sync props/DOM measurements). Prettier rules run via ESLint (`prettier/prettier: error`).

---

## Testing

`vitest` (jsdom) + Testing Library. Config `vitest.config.ts`, setup `vitest.setup.ts` (auto-cleanup). Run `npm run test` (or `./node_modules/.bin/vitest run`). **Tests are in scope** (see [testing-strategy.md](../../docs/agent/testing-strategy.md)); keep them deterministic and anti-theater (a test must fail when its target breaks).

Specs (`tests/`):

- **i18n** — `i18n-utils.test.ts` (`getNestedValue` dot-path + `applyParams` substitution), `i18n-server.test.ts`.
- **resume document** — `section-registry.test.tsx` (every template renders every `SectionKind` from data, honours each bullet style, and omits hidden sections), `template-registration.test.ts` (template registry + font presets), `resume-content.test.ts`.
- **lib/utils** — `keyword-matcher.test.ts`, `html-sanitizer.test.ts` (XSS whitelist), `download-utils.test.ts`, `resume-draft-storage.test.ts`, `tracker-column-visibility.test.ts`.
- **lib/api** — `api-client.test.ts` (URL resolution, timeout/AbortError; `fetch` stubbed), `api-resume.test.ts`, `api-config.test.ts`, `api-tracker.test.ts`.
- **components / lifecycles** — `diff-preview-modal.test.tsx`, `regenerate-wizard.test.tsx`, the `resume-builder-*`, `resume-viewer-*`, `dashboard-*`, `resume-wizard-*` and `wizard-hook-lifecycle` specs.

Pure logic (i18n, utils, api) is tested directly with stubbed `fetch`/`t`; component specs render via Testing Library. `.github/workflows/tests.yml` runs this suite plus `tsc --noEmit` and eslint on pushes to `main`/`dev`; there is no pre-push hook.

---

## Documentation by Task

| Task                                | Docs                                                                                                                                                                                                                                                                                                                                         |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend architecture / user flow   | [frontend-architecture.md](../../docs/agent/architecture/frontend-architecture.md), [frontend-workflow.md](../../docs/agent/architecture/frontend-workflow.md)                                                                                                                                                                               |
| Coding conventions                  | [coding-standards.md](../../docs/agent/coding-standards.md)                                                                                                                                                                                                                                                                                  |
| API contracts                       | [front-end-apis.md](../../docs/agent/apis/front-end-apis.md), [api-flow-maps.md](../../docs/agent/apis/api-flow-maps.md)                                                                                                                                                                                                                     |
| Swiss design system (MANDATORY)     | [pack README](../../docs/portable/swiss-design-system/README.md), [tokens](../../docs/portable/swiss-design-system/tokens.md), [components](../../docs/portable/swiss-design-system/components.md), [anti-patterns](../../docs/portable/swiss-design-system/anti-patterns.md), [layouts](../../docs/portable/swiss-design-system/layouts.md) |
| Next.js performance (REQUIRED)      | [pack README](../../docs/portable/nextjs-performance/README.md), [checklist](../../docs/portable/nextjs-performance/checklist.md)                                                                                                                                                                                                            |
| Resume templates / PDF              | [resume-templates.md](../../docs/agent/features/resume-templates.md), [template-system.md](../../docs/agent/design/template-system.md), [pdf-template-guide.md](../../docs/agent/design/pdf-template-guide.md), [adding-resume-templates.md](../../docs/agent/features/adding-resume-templates.md)                                           |
| Resume sections / document contract | [custom-sections.md](../../docs/agent/features/custom-sections.md)                                                                                                                                                                                                                                                                           |
| AI enrichment                       | [enrichment.md](../../docs/agent/features/enrichment.md)                                                                                                                                                                                                                                                                                     |
| JD matching                         | [jd-match.md](../../docs/agent/features/jd-match.md)                                                                                                                                                                                                                                                                                         |

---

## Out of Scope (do not modify without explicit request)

- `.github/workflows/`, CI/CD, Docker behavior
- Existing tests (no removal/disabling)
- `next.config.ts` rewrites / proxy behavior unless the task is about it

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
