# Backend Guide

> Lean, local-first FastAPI app for resume tailoring.

## Tech Stack

| Component      | Technology                                |
| -------------- | ----------------------------------------- |
| Framework      | FastAPI                                   |
| Database       | SQLite (SQLAlchemy 2.0 async + aiosqlite) |
| AI             | LiteLLM (100+ providers)                  |
| Doc Parsing    | markitdown                                |
| Validation     | Pydantic                                  |
| Key encryption | Fernet (`cryptography`)                   |

## Directory Structure

```
apps/backend/app/
├── main.py         # Entry point (lifespan: Alembic upgrade, TinyDB→SQLite import, legacy-key fold-in)
├── config.py       # Settings from env/file; encrypted API-key read/write
├── crypto.py       # Fernet encrypt/decrypt for API keys at rest
├── database.py     # Async SQLAlchemy/SQLite facade (returns plain dicts)
├── models.py       # SQLAlchemy declarative Base + ORM models
├── db_engine.py    # SQLite engine/session factories (async + sync) + PRAGMAs
├── llm.py          # Multi-provider LLM (JSON retries + output-budget escalation)
├── ai_events.py    # Bounded in-process tail of recent AI failures (diagnostics)
├── deps.py         # FastAPI dependencies (resolve_workspace_id → X-Workspace-Id)
├── preview.py      # Preview fingerprints/claims for tailoring confirmation
├── latex/          # LaTeX export: escape.py (the escaping boundary),
│                   #   render.py (Jinja → .tex), compile.py (engine detection +
│                   #   sandboxed run), templates/ (*.tex.j2)
├── routers/        # health, config, resumes, jobs, applications, enrichment,
│                   #   workspaces, versions, diff, tex, resume_wizard
├── services/       # parser, improver, refiner, resume_preservation,
│                   #   document_walk, document_diff, ats, cover_letter,
│                   #   interview_prep, resume_wizard
├── schemas/        # Pydantic models (document.py = the resume contract,
│                   #   models.py, enrichment.py, applications.py, versions.py,
│                   #   workspaces.py, refinement.py, resume_wizard.py, tex.py)
├── scripts/        # migrate_tinydb_to_sqlite.py (one-time importer)
└── prompts/        # templates.py, schema.py (document shape + allowed paths),
                    #   enrichment.py, refinement.py, resume_wizard.py

apps/backend/alembic.ini      # Alembic config (script_location = ./migrations)
apps/backend/migrations/      # Alembic env.py + versions/
```

## Database Operations

`database.py` is an async `Database` facade (global `db` singleton). Methods keep the
same names/signatures as the old TinyDB wrapper but return **plain dicts** (never ORM
rows). ORM models are in `models.py`; engine plumbing is in `db_engine.py`.

```python
await db.create_resume(content, content_type, filename, is_master, processed_data)
await db.get_resume(resume_id) → dict | None
await db.list_resumes() → list[dict]
await db.update_resume(resume_id, updates)
await db.delete_resume(resume_id) → bool
await db.set_master_resume(resume_id)            # Demote + promote in one transaction
await db.claim_resume_processing(resume_id)      # Rotate private operation token
await db.finish_resume_processing(...)           # Token-guarded ready/failed commit
await db.create_job(content, resume_id)
await db.create_application(...) / list_applications / bulk_update_applications
get_api_key_ciphertexts() / replace_api_keys(...)  # sync; encrypted api_keys table
```

**Tables:** `workspaces`, `resumes`, `resume_versions`, `jobs`, `improvements`, `applications`, `tailoring_previews`, `api_keys` (encrypted).
DB file: `data/resume_matcher.db`.

### Workspaces

A **workspace** is a named owner profile ("Tom", "Lior — Hebrew"), not a tenant — the
product has no auth. `resumes`, `jobs` and `applications` each carry `workspace_id`;
exactly one workspace row has `is_default = 1`.

Requests select one with the `X-Workspace-Id` header, resolved by
`app/deps.py::resolve_workspace_id`. A missing **or unknown** id falls back to the
default workspace: the Playwright print route is fetched by Chromium without app
headers, and the browser's stored id can outlive a deleted workspace.

Scoping applies to list/create/master paths only; fetch-by-id is not filtered, so a
direct link (or the print route) still resolves a document from any workspace.
`ux_resumes_workspace_master` replaces the old database-global single-master index.

### The master resume

Exactly one resume per workspace has `is_master = 1`, and
`ux_resumes_workspace_master` is the final guarantee. Two paths set it:

- **creation** — the first upload or wizard finalize in a workspace
  (`create_resume_atomic_master`), or a replacement upload while the current
  master is stuck `failed`/`processing`;
- **promotion** — `POST /resumes/{resume_id}/master`, workspace-scoped through
  `X-Workspace-Id`, which calls `db.set_master_resume()`: the demotion of the
  old master and the promotion of the target share **one transaction** (the
  demotion is flushed first, so the partial unique index never sees two
  masters, and a failure leaves the old master in place). `404` when the resume
  does not exist or belongs to another workspace, `409` unless
  `processing_status == "ready"`; `200` returns
  `{resume_id, is_master, previous_master_id}` (`SetMasterResumeResponse`),
  with `previous_master_id` `null` when there was no master or the target
  already was it.

The demoted resume is **kept as an ordinary resume** — not deleted, not
archived. Only the flag moves: it keeps its document, version timeline, `.tex`
override, template settings, cover letter, outreach message, interview prep and
tracker links, reappears in `GET /resumes/list` (which filters the master out
unless `include_master=true`), and can be promoted back with the same call.

Any `ready` resume may be promoted, **a tailored one included**, and `parent_id`
is deliberately preserved — it records where the document came from and gates
the cover-letter, outreach, interview-prep and job-description routes, so
clearing it would silently disable them. What promoting a tailored resume does
change is the tailoring baseline: `get_master_resume()` is the source of truth
the improve routes feed to `refine_resume`, and `app/prompts/refinement.py`
tells the model to verify every claim against it, so a job-biased document
becomes the anti-hallucination reference for every later tailoring.

`GET /resumes?resume_id=` returns `is_master` (`ResumeData`). That flag is the
authoritative answer; the browser's cached `master_resume_id` is a fallback only
and can name a resume that has since been demoted.

### Schema migrations (Alembic)

`init_models_sync` (called once from the lifespan via `db.ensure_ready()`) brings the
database to head:

- **Empty file** → built from the models and stamped at head (cheap; every test builds
  its own database). `uv run alembic check` is what keeps models and revisions in step.
- **Pre-Alembic database** → patched to the baseline shape, stamped `0001_baseline`,
  then upgraded.
- **Alembic-managed** → upgraded only when behind head.

Add a revision with `cd apps/backend && uv run alembic revision --autogenerate -m "…"`.
Verify models and revisions agree with `uv run alembic upgrade head && uv run alembic check`
(`check` needs an already-upgraded database to compare against).
The `Dockerfile` copies `alembic.ini` and `migrations/` alongside `app/`.

**Two engines, one file:** a module-level **async** engine serves the document tables +
`applications`; a **sync** engine serves the encrypted `api_keys` table (read on the
synchronous LLM hot path). Both apply PRAGMAs `journal_mode=WAL`, `foreign_keys=ON`,
`busy_timeout`. Master changes reserve SQLite writes with `BEGIN IMMEDIATE`; a partial unique index
provides the final single-master constraint across connections. Jobs' dynamic fields
(`job_keywords`, `job_keywords_hash`, `company`/`role`, `preview_hash`,
`preview_prompt_id`, and `preview_hashes`) live in `metadata_json`, flattened on read. Preview
identity, fingerprints, claims and replay responses live in `tailoring_previews`.
See [storage transactions](storage-transactions.md) and [confirmation](../features/preview-confirmation.md).

### Encrypted API keys & migration

- **Keys** (`crypto.py`): Fernet-encrypted, per-provider, in the `api_keys` table. Secret
  at `data/.secret_key` (`chmod 600`, gitignored, atomic write; plaintext only in memory).
  `config.py` injects decrypted keys at read time and strips them on save, so secrets
  never reach `config.json`. Set via `POST /config/api-keys`; `PUT /config/llm-api-key` no
  longer persists a key.
- **Migration** (`scripts/migrate_tinydb_to_sqlite.py`): runs on lifespan startup. Imports
  a legacy `data/database.json` (TinyDB) into SQLite if present, then renames it
  `database.json.migrated`. Idempotent. `migrate_legacy_keys()` likewise folds legacy
  plaintext keys into the encrypted store.

## The resume document (schema version 2)

Structured resume content — stored in `resumes.processed_data`, accepted by
`PATCH /resumes/{id}`, returned by every read — is one Pydantic model:
`app/schemas/document.py::ResumeDocument`.

```python
ResumeDocument(schemaVersion=2, header=Header(...), sections=[Section(...), ...])
```

Sections, their headings, their order and their shapes are **data**. Nothing in
the application enumerates resume sections: consumers switch on
`SectionKind` and iterate `document.sections`.

| Model | Notes |
| ----- | ----- |
| `Header` | `name`, `headline`, `contacts` — **not** a section; templates render it outside the section loop |
| `Section` | `key` (slug, unique, used in change paths), `heading` (free text), `headingI18nKey`, `kind`, `visible`, `column` (`main`/`side`), plus the one content field its `kind` selects |
| `SectionKind` | `text` → `section.text`; `entries` → `section.entries`; `tags` → `section.tags`; `groups` → `section.groups` |
| `Entry` | `id`, `title`, `subtitle`, `meta`, `period`, `links`, **`summary`** (a paragraph) and **`bullets`** — both, on the same entry |
| `Bullet` | `text` + its own `style: bullet \| plain` |
| `TagGroup` | `label` + `values` |

Design properties worth knowing before you touch this:

- **Order is list order.** There is no order field to reindex.
- **`extra="forbid"` on every model.** An unknown field is a validation error.
  The v1 models inherited Pydantic's `extra='ignore'`, so every write silently
  discarded sections the code did not know about; forbidding extras is the point
  of the exercise.
- **A user-created section is an ordinary section.** There is no privileged
  built-in set, so nothing special-cases one.

### Traversal

`app/services/document_walk.py` is the shared, section-agnostic traversal —
use it instead of reaching into sections by name:

| Helper | Yields |
| ------ | ------ |
| `iter_sections(doc, kind=None)` | sections, optionally one kind |
| `iter_entries(doc)` | `(section, index, entry)` for every entry |
| `skill_values(doc)` | every short value across `tags` + `groups` sections |
| `document_text_fragments(doc)` | every user-authored string in the body (header excluded) |
| `section_path` / `entry_paths` / `skill_list_paths` | change paths for a section, an entry, the short-value lists |
| `sections_of` / `entries_of` / `bullet_texts` | the dict-level equivalents, for the AI apply path that mutates raw JSON before re-validating |

### AI change paths

The tailoring LLM returns targeted changes, each a path plus an action. The
allowlist is **generated per document** by `improver.build_allowed_paths` from
that document's sections and their kinds:

```
sections.<key>.text                          # kind == text
sections.<key>.entries[i].summary            # kind == entries
sections.<key>.entries[i].bullets
sections.<key>.entries[i].bullets[j].text
sections.<key>.tags                          # kind == tags
sections.<key>.groups[i].values              # kind == groups
```

This is why a section the user created is AI-editable: the allowlist is a
function of the document, not a fixed list of names. `sections.<key>` resolves a
section **by key** — the path segment matches the list item whose `key` equals
it — so a reorder cannot retarget a different section. Identity and structure
(`header.*`, `schemaVersion`, and the fields `id`, `key`, `kind`, `heading`,
`headingI18nKey`, `visible`, `column`, `title`, `subtitle`, `meta`, `period`,
`links`, `label`, `style`) are never editable. `append` targets a bullet list
only; a short value must come through the verified `add_skill` action.

Full wire contract: [front-end-apis.md](../apis/front-end-apis.md#ai-change-paths).
Section semantics from the user's side: [custom-sections.md](../features/custom-sections.md).

### Reading older rows

`migrate_document(raw)` projects a resume stored under schema version 1 (fixed
`personalInfo`/`workExperience`/… keys, `sectionMeta`, `customSections`,
parallel `description`/`descriptionStyles` arrays) onto the v2 document on
read. It is the only place those names survive; nothing writes them.

### Comparing two documents

`app/services/document_diff.py` is the **only** comparison engine, and
`app/schemas/diff.py` is its wire shape. It is a tree diff: sections pair with
sections, entries pair inside their section, and only leaves are compared as
text — so a renamed heading is `renamed` and a reordered entry is `moved`,
instead of a delete plus an add.

| Export | Used by |
| ------ | ------- |
| `diff_documents(base, head, context=2)` → `DocumentDiff` | `POST /diff` (`app/routers/diff.py`) and the tailoring responses, which embed the result as `ImproveResumeData.diff` |
| `diff_value_lists(base, head, path=…, kind=…)` → `list[DiffRow]` | `app/routers/enrichment.py`, for `RegeneratedItem.rows` |
| `merge_accepted(base, head, accepted_paths)` → `ResumeDocument` | `POST /resumes/improve/confirm`, when `accepted_paths` names a subset |
| `diff_tex_sources(base_tex, head_tex, context=2)` → `list[DiffRow]` | `POST /diff` with `mode="tex"` |

Rows are keyed by the AI change-path grammar above, which is what lets one row
be accepted on its own: a partial confirm re-runs `merge_accepted` and then the
same preservation chain and payload validation as a whole preview. Only content
leaves are selectable — structure comes from the source document.

`app/routers/diff.py` resolves each side from a ref (`{resume_id}` or
`{version_id}`) and refuses a comparison whose sides sit in different
workspaces (`403`), because a diff reads two documents at once.

Pairing rules, thresholds, statuses and the three UI surfaces:
[document-diff.md](../features/document-diff.md).

## LaTeX export (`app/latex/`)

A second render target beside the Chromium/Playwright PDF, from the same
document. Four pieces, in dependency order:

| Module | Responsibility |
| ------ | -------------- |
| `escape.py` | `escape_tex` — the boundary every user string crosses. Backslash first, because every other replacement introduces backslashes |
| `render.py` | Jinja2 with LaTeX-safe delimiters (`<< >>`, `<% %>`, `<# #>`); `autoescape` off, so the `tex` filter is mandatory per site. `LATEX_TEMPLATES` = `tex-classic`, `tex-compact` |
| `compile.py` | `latex_engine()` (`RESUME_MATCHER_LATEX_ENGINE`, else tectonic → latexmk → xelatex → pdflatex) and `compile_tex_to_pdf()` — temp cwd, `-no-shell-escape`, `openin_any`/`openout_any=p`, 120s timeout |
| `templates/` | `_document.tex.j2` shared body + one preamble per template |

`resumes.tex_source` (migration `0004_tex_source`) is NULL for generated
source and holds the user's own `.tex` otherwise; a `PUT` checkpoints it on the
version timeline as `origin="tex_edit"`. No engine installed is a **503**, not
a 500 — the capability is missing, not the request. Full contract:
[latex-export.md](../features/latex-export.md).

## Template settings (`resumes.template_settings`)

The template and formatting choice belongs to the **resume**, not the browser:
the viewer and both export routes render what the user designed for that
resume, on any device. `resumes.template_settings` (migration
`0005_template_settings`) is a nullable JSON column holding the frontend's
`TemplateSettings` object verbatim.

- **NULL means "no choice stored yet"**, not "the defaults". A client reading
  NULL keeps its own last-used settings, so opening a resume that predates the
  column never resets how it looks. `_parse_template_settings`
  (`app/routers/resumes.py`) degrades an unreadable stored payload to `None`
  with a logged warning for the same reason — presentation must not fail a
  document fetch.
- **The payload is validated, not trusted.**
  `PUT /resumes/{id}/template-settings` binds the body to `TemplateSettings`
  (`app/schemas/template_settings.py`): camelCase names mirroring the frontend
  type, `extra="forbid"` at every level, margins 5–25 mm, the four spacing axes
  (`section`, `item`, `lineHeight`, `bulletLeadIn`) at levels 1–9, the two type
  axes (`base`, `headerScale`) at levels 1–5 — `extarticle`/`extsizes` offers
  8/9/10/11/12pt and nothing below 8pt, so there is no step to add downward —
  and closed literals for `template`, `pageSize`, the two
  font families and `accentColor`. Unknown resume → 404, anything outside those
  bounds → 422.
- **`settingsVersion` marks the level vocabulary.** It is `Literal[2] = 2` on
  `TemplateSettings`; a stored payload without it is v1, whose spacing levels
  ran 1–5. v1 and v2 numbers overlap, so the payload alone is ambiguous and the
  marker is the only disambiguator. `_parse_template_settings` upgrades a v1
  payload on read by adding 2 to each spacing level — the old 1–5 become 3–7,
  which are the same physical lengths, so nothing reflows — leaving the font
  levels and every other field alone. The frontend's
  `readTemplateSettings` does the identical thing to `localStorage`.
  This is not document history: see the next bullet.
- **Not part of document history.** Presentation is not content, so the column never reaches
  `commit_resume_version` and `resume_versions` has no such field: restoring an
  older document does not revert how the resume looks, and a document `PATCH`
  leaves the settings untouched. Contrast `tex_source`, which *is* versioned
  because a source edit is authored content.
- **Tailoring inherits it.** `POST /resumes/improve/confirm` and the one-shot
  `POST /resumes/improve` copy the parent's value onto the resume they create,
  so a tailored copy is never silently re-themed.
- **The ids live in the schema module.** `HTML_TEMPLATES` (the seven
  Chromium-rendered templates) and `TEX_TEMPLATES` (`tex-classic`,
  `tex-compact`) are defined in `app/schemas/template_settings.py`;
  `app/routers/resumes.py` imports `HTML_TEMPLATES` from there for the 400 that
  `GET /resumes/{id}/pdf` raises on a LaTeX template, so the stored value, the
  validator and the export guard cannot drift apart.

## Configuration ownership

`Settings.data_dir` owns `resume_matcher.db`, `config.json` and `.secret_key`.
JSON settings use a same-directory temporary file and atomic replacement; key
updates use the encrypted SQLite table. These are separate persistence operations.
Tests install a temporary DATA_DIR before application imports and deny external
network by default, so normal test runs do not read or overwrite developer settings.

## LLM Features

| Feature         | Description                                                                                                                  |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| API Key Passing | Direct to litellm (avoids race conditions)                                                                                   |
| JSON Mode       | Auto-enabled for supported providers                                                                                         |
| Retry Logic     | Bounded task-schema content retries plus a separate transport-error policy; [exact policy](../llm-integration.md)            |
| Token budgets   | `DEFAULT_JSON_MAX_TOKENS` 8192; resume parsing asks `RESUME_JSON_MAX_TOKENS` 24,576; both clamped by `get_safe_max_tokens`    |
| Truncation      | `finish_reason == "length"` or an unclosed object raises `TruncatedCompletionError`; the retry doubles the budget (≤ 65,536)  |
| Timeouts        | 30s health; completion/JSON base 120s/180s scale by tokens/provider and are capped by the remaining operation deadline       |

## Prompt Guidelines

1. Use `{variable}` for substitution (single braces)
2. Include JSON schema examples
3. End with "Output ONLY the JSON object"

## API Endpoints Quick Ref

```
GET  /api/v1/health              # liveness probe (no LLM call)
GET  /api/v1/status              # Full status (LLM + DB isolated; 200 on partial failure)
GET/PUT /api/v1/config/llm-api-key            # no longer persists a key
GET/POST/DELETE /api/v1/config/api-keys       # per-provider encrypted keys
POST /api/v1/resumes/upload      # PDF/DOC/DOCX/TEX
GET  /api/v1/resumes?resume_id=   # ResumeDocument in data.processed_resume
PATCH /api/v1/resumes/{id}        # body: a complete ResumeDocument
POST /api/v1/resumes/improve/preview  + /improve/confirm   # tailor (LLM), then persist
POST /api/v1/resumes/improve     # legacy one-shot tailor (LLM)
GET  /api/v1/resumes/{id}/pdf
PUT  /api/v1/resumes/{id}/template-settings   # the resume's own template/formatting choice
GET  /api/v1/resumes/tex/capabilities         # engine name, can_compile, template ids
GET/PUT/DELETE /api/v1/resumes/{id}/tex       # LaTeX source: generated | override
GET  /api/v1/resumes/{id}/tex/source          # .tex download
GET  /api/v1/resumes/{id}/tex/pdf             # compile (503 no engine, 422 bad source)
DELETE /api/v1/resumes/{id}
POST /api/v1/resumes/{id}/master  # promote to workspace master (404 unknown/other workspace, 409 not ready)
GET/PATCH/DELETE /api/v1/versions/{id}        # resume version history
POST /api/v1/diff                # compare two refs (resume/version), mode document|tex
GET/POST /api/v1/workspaces (+ PATCH/DELETE /{id})
POST /api/v1/resume-wizard/turn  + /finalize
GET  /api/v1/applications        # Kanban tracker: grouped list (+ POST/PATCH/DELETE/bulk)
```

## Data Flow

**Upload:** Bounded file read → container validation → worker-thread MarkItDown
(or LaTeX source extraction for `.tex`) → bounded Markdown → LLM parse →
deterministic date/link restoration → token-guarded JSON/status commit → SQLite
(via `db`)

**Preview:** Resume + Job → keywords → targeted differences/refinement → registered preview.
**Confirm:** validate/claim preview → optional outputs → atomic resume/improvement/response commit.
Successful retries replay the recorded result. Routers call
services; services call `app/llm.py`; persistence goes through the async `db` facade.
`/improve/confirm` also best-effort auto-creates an `applied` card in the tracker.

### Upload validation and resource policy

- Supported formats are PDF (`.pdf`), legacy Word (`.doc`), Office Open XML Word
  (`.docx`) and LaTeX source (`.tex`). `DOCUMENT_TYPES_BY_EXTENSION` maps each
  extension to a **set** of acceptable MIME types, because `.tex` has no single
  registered type: browsers send `text/x-tex`, `application/x-tex`, `text/plain`
  or `application/octet-stream` depending on the OS. Extension and MIME must
  still agree — `text/plain` is accepted for `.tex` and rejected for `.pdf` —
  and a mismatch returns 400 `Upload a valid PDF, DOC, DOCX, or TEX file.`
  while an entirely unknown type returns 400
  `Invalid file type: {type}. Allowed: PDF, DOC, DOCX, TEX`.
- MIME alone does not establish a binary format either: PDF structure, the DOC
  compound-file header, or the DOCX ZIP/package must validate.
- A `.tex` upload is read as source, not converted: `_extract_tex_source`
  decodes UTF-8 (invalid bytes are a validation error, so a binary file renamed
  `.tex` is rejected), strips `%` comments while preserving `\%`, and keeps only
  the `\begin{document}`…`\end{document}` body when those markers are present.
  MarkItDown is skipped — it would return the preamble as body text — and the
  **TeX engine is never invoked**: the compile sandbox exists for source the app
  generates, and uploaded source stays data. This is also the lossless ingest
  path, since the source still carries `\href` links and `\textbf` emphasis.
- Raw input is read in 64 KiB chunks and capped at 4 MiB. DOCX packages permit
  at most 1,024 members and 16 MiB total expanded bytes, checked from metadata
  and again while streaming members. Extracted UTF-8 text is capped at 2 MiB
  before prompt construction.
- MarkItDown validation/conversion runs outside the event loop with at most two
  concurrent workers and a 120-second caller deadline. On cancellation or
  timeout, the caller returns promptly; the worker retains its capacity slot and
  removes its temporary file in `finally`. Threads cannot be forcibly terminated,
  so a stuck converter retains its slot until it exits.
- Each upload/retry claims a private processing token. Only the latest token may
  commit `ready` or `failed`; superseded requests receive 409. If the row is
  deleted while parsing, completion receives 404 and does not recreate or update it.

### PDF link recovery

MarkItDown reads only a PDF's text stream, where a hyperlink is at best its
anchor text and at worst an icon glyph (a FontAwesome private-use character, or
pdfminer's `(cid:NNN)` fallback), so a LaTeX-built CV's GitHub, LinkedIn and
project URLs never reached the model. The URLs are in the file, in each page's
`/Annots` array, which the text extractor never visits.

- `_extract_pdf_links` (pdfminer.six) resolves every annotation's `/A` → `/URI`,
  accepts only the `http`, `https`, `mailto` and `tel` schemes, caps a URI at
  2,048 characters and a document at 100 links, and de-duplicates on the
  normalised URL (lowercased host, no trailing slash) per page. Any failure logs
  a warning and yields no links: a malformed `/Annots` must never fail an upload
  that would otherwise parse.
- `kind` is inferred in Python, never asked of the model — `mailto:` → `email`,
  `tel:` → `phone`, a `github.com`/`linkedin.com` host → `github`/`linkedin`,
  anything else → `website`. `scope` is geometric: `header` for a link on page 1
  within the top 15% of the page, `entry` below it. `context` is the laid-out
  text line sharing the most height with the annotation rectangle, with icon
  glyphs stripped and truncated to 120 characters.
- `format_links_block` appends the result to the extracted text as a
  `## Links extracted from the PDF file` block — one
  `- kind=… scope=… context="…" url=…` row per link, in document order — and the
  2 MiB text cap is re-checked afterwards. `PARSE_RESUME_PROMPT` declares the
  block ground truth rather than resume content and asks for each URL to be
  placed on its contact or entry.
- The block lives **inside** the stored text on purpose: the upload route stores
  that string as the resume's `content` (`content_type="md"`, and as
  `original_markdown`), and `POST /api/v1/resumes/{id}/retry-processing` re-runs
  the LLM on that stored markdown. Links passed out of band would be lost on the
  next parse.
- `restore_links_from_markdown` is the deterministic backstop and the sibling of
  `restore_dates_from_markdown`: `parse_resume_to_json` calls it immediately
  after the date restore and before final `ResumeDocument` validation, so
  anything it adds gets an id there. It re-reads the block and only ever adds
  what is missing — a header link fills an existing same-kind contact's empty
  `url` or appends a new contact, and an entry link attaches to the entry whose
  normalised title matches its context, or is dropped rather than guessed.

## Error Handling

Log details server-side, generic messages to clients:

```python
except Exception as e:
    logger.error(f"Failed: {e}")
    raise HTTPException(500, "Operation failed.")
```

## Running

```bash
cd apps/backend
cp .env.example .env
uv run uvicorn app.main:app --reload --port 8000
```

## Adding New Endpoints

1. Create the router in `app/routers/` (or extend an existing one).
2. Add request/response models to `app/schemas/` — a new file per feature area;
   `app/schemas/models.py` holds the resume/improve envelopes. Anything carrying
   structured resume content uses `ResumeDocument` from
   `app/schemas/document.py`; do not redeclare a resume shape.
3. Take `workspace_id: WorkspaceId` (`app/deps.py`) on any endpoint that lists
   or creates workspace-scoped rows.
4. Register the router in `app/routers/__init__.py`, mounted under `/api/v1`.
5. If the endpoint touches the schema, add an Alembic revision (see
   [Schema migrations](#schema-migrations-alembic)).

Legacy `.doc` files pass compound-file header validation, but the bundled MarkItDown DOCX converter does not guarantee binary Word conversion. Convert legacy Word documents to PDF or DOCX for reliable upload.
