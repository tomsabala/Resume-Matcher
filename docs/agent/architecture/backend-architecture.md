# Backend Architecture

> FastAPI + Python 3.13+ | SQLite (SQLAlchemy 2.0 async + aiosqlite) | LiteLLM multi-provider

## Directory Structure

```
apps/backend/app/
├── main.py              # FastAPI entry point (lifespan: TinyDB→SQLite import, legacy-key fold-in)
├── config.py            # Pydantic settings; encrypted API-key read/write
├── crypto.py            # Fernet encrypt/decrypt for API keys at rest
├── database.py          # Async SQLAlchemy/SQLite facade (returns plain dicts)
├── models.py            # SQLAlchemy declarative Base + ORM models
├── db_engine.py         # SQLite engine/session factories (async + sync) + PRAGMAs
├── llm.py               # LiteLLM multi-provider
├── ai_events.py         # In-process bounded tail of recent AI failures (diagnostics)
├── pdf.py               # Playwright PDF rendering
├── routers/             # API endpoints (health, config, resumes, jobs, applications, enrichment)
├── services/            # parser.py, improver.py, cover_letter.py
├── schemas/             # Pydantic models (models.py, applications.py)
├── scripts/             # migrate_tinydb_to_sqlite.py (one-time importer)
└── prompts/templates.py # LLM prompts
```

## API Endpoints

### Health, status & diagnostics

| Method | Endpoint                             | Description                                                                                           |
| ------ | ------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/health`                     | Liveness probe (no LLM call)                                                                          |
| GET    | `/api/v1/status`                     | Full system status (LLM probe + DB stats, each isolated → 200 with degraded state on partial failure) |
| GET    | `/api/v1/diagnostics/ai-failures`    | Recent AI failures, newest first → `{failures: [...], dismissed: 0}`                                  |
| DELETE | `/api/v1/diagnostics/ai-failures`    | Drop the tracked failures → `{failures: [], dismissed: N}`                                            |

`app/ai_events.py` holds the failure tail the two diagnostics routes read: an
in-process `deque` of at most 20 records (`MAX_TRACKED_AI_FAILURES`), guarded
by a lock, with **no persistence** — it is a diagnostic tail, not an audit log,
so a restart empties it. Each record stores only the shape of the failure
(`id`, `at`, `operation`, `kind`, `detail` truncated to 300 characters, `model`,
`provider`, `attempts`, `max_tokens`) and never a prompt, resume, job
description or model output, which is what makes the payload safe to return to
a client. `complete_json` records a **terminal** failure only; a retry that
recovered is not tracked. See the [record shape and `kind`
vocabulary](../apis/front-end-apis.md#ai-diagnostics-libapidiagnosticsts).

### Configuration

| Method          | Endpoint                     | Description                           |
| --------------- | ---------------------------- | ------------------------------------- |
| GET/PUT         | `/api/v1/config/llm-api-key` | LLM config (no longer persists a key) |
| POST            | `/api/v1/config/llm-test`    | Test connection                       |
| GET/POST/DELETE | `/api/v1/config/api-keys`    | Per-provider encrypted API keys       |

### Resumes

| Method | Endpoint                            | Description                                  |
| ------ | ----------------------------------- | -------------------------------------------- |
| POST   | `/resumes/upload`                   | Upload PDF/DOC/DOCX/TEX                      |
| GET    | `/resumes?resume_id=`               | Fetch resume (incl. `data.template_settings`) |
| GET    | `/resumes/list`                     | List all                                     |
| POST   | `/resumes/improve`                  | Tailor for job (LLM)                         |
| PATCH  | `/resumes/{id}`                     | Update                                       |
| PUT    | `/resumes/{id}/template-settings`   | Store this resume's template/formatting choice (404 unknown resume, 422 invalid) |
| GET    | `/resumes/{id}/pdf`                 | Download PDF                                 |
| DELETE | `/resumes/{id}`                     | Delete                                       |

### Jobs

| Method | Endpoint       | Description           |
| ------ | -------------- | --------------------- |
| POST   | `/jobs/upload` | Store job description |
| GET    | `/jobs/{id}`   | Fetch job             |

### Applications (Kanban tracker)

| Method | Endpoint                    | Description                                 |
| ------ | --------------------------- | ------------------------------------------- |
| GET    | `/applications`             | All cards grouped by column (7 status keys) |
| POST   | `/applications`             | Manual add (creates job + card)             |
| GET    | `/applications/{id}`        | Card + JD + resume (resume null if deleted) |
| PATCH  | `/applications/{id}`        | Update status/position/notes/company/role   |
| PATCH  | `/applications/bulk`        | Move many cards to one column               |
| DELETE | `/applications/{id}`        | Delete one card                             |
| POST   | `/applications/bulk-delete` | Delete many cards                           |

## Database (`database.py`, `models.py`, `db_engine.py`)

**SQLite** via SQLAlchemy 2.0 async (`aiosqlite`). DB file: `data/resume_matcher.db`.
`database.py` is an async `Database` facade (global `db` singleton) — same method
names/signatures as before, but it returns **plain dicts**, never ORM rows.
ORM models live in `models.py` (declarative `Base` + `Resume`/`Job`/`Improvement`/`Application`/`TailoringPreview`/`ApiKey`);
engine/session plumbing lives in `db_engine.py`.

Tables: `resumes`, `jobs`, `improvements`, `applications`, `tailoring_previews`, `api_keys` (encrypted).

Beside the document, `resumes` carries two nullable presentation columns:
`tex_source` (migration `0004_tex_source`), a hand-edited `.tex` override, and
`template_settings` (migration `0005_template_settings`), the resume's own
template and formatting choice stored as the frontend's camelCase
`TemplateSettings` JSON and validated by `app/schemas/template_settings.py`.
NULL in `template_settings` means "no choice stored yet", so the client keeps
its last-used settings rather than being reset to defaults. Unlike
`tex_source`, it is **not** carried into `resume_versions`: presentation is not
content, so restoring an older document must not revert how the resume looks.
A tailored resume is created with a copy of its parent's value.

```python
await db.create_resume(content, content_type, filename, is_master, processed_data)
await db.get_resume(resume_id) → dict | None
await db.update_resume(resume_id, updates) → dict
await db.delete_resume(resume_id) → bool
await db.set_master_resume(resume_id)            # One master per workspace; demote + promote in one txn
await db.create_application(...) / list_applications / update_application / bulk_*
await db.get_stats() → {total_resumes, total_jobs, total_improvements, total_applications}
get_api_key_ciphertexts() / replace_api_keys(...)  # sync; encrypted api_keys table
```

**Two engines, one file (`db_engine.py`):** a module-level **async** engine serves
the document tables + `applications`; a **sync** engine serves the encrypted
`api_keys` table, which is read on the synchronous LLM hot path
(`get_llm_config` → `load_config_file` → `resolve_api_key`) so async isn't threaded
through `llm.py`. Both apply PRAGMAs `journal_mode=WAL`, `foreign_keys=ON`,
`busy_timeout` on connect.

**Single-master invariant** is enforced by a partial unique index on `is_master`
(`ux_resumes_workspace_master`, scoped per workspace).
Master replacement and tracker read-modify-write operations reserve SQLite writes
with `BEGIN IMMEDIATE`, including across Database instances. Master-ness is not
fixed at creation: `POST /resumes/{id}/master` promotes any `ready` resume
through `set_master_resume()`, demoting the previous master to an ordinary
resume (nothing else about it changes) in the same transaction — see
[the master resume](backend-guide.md#the-master-resume).
**Jobs' dynamic fields** (`job_keywords`, `job_keywords_hash`, `company`/`role`,
`preview_hash`, `preview_hashes`, and `preview_prompt_id`) are stored in
`metadata_json` and flattened on read; immutable preview identity, fingerprints,
claims and cached confirmation responses live in `tailoring_previews`.
See [storage transactions](storage-transactions.md) and [confirmation](../features/preview-confirmation.md).
`Application` dedupes on `(job_id, resume_id)` via a `UniqueConstraint`.

### Migration & encrypted keys

- **One-time importer** (`app/scripts/migrate_tinydb_to_sqlite.py`): runs on lifespan
  startup. If a legacy `data/database.json` (TinyDB) exists and SQLite is empty, it
  imports the rows, then renames the file `database.json.migrated` (rollback artifact).
  Idempotent: skips if SQLite already has rows.
- **Encrypted API keys** (`app/crypto.py`): Fernet symmetric encrypt/decrypt. The
  secret lives at `data/.secret_key` (auto-generated, `chmod 600`, gitignored, atomic
  write); plaintext exists only in memory. Per-provider ciphertexts live in the
  `api_keys` table. `app/config.py` reads/writes them (atomic `replace_api_keys`);
  `migrate_legacy_keys()` folds any legacy plaintext keys into the encrypted store on
  startup (idempotent, non-clobbering).

## LLM Integration (`llm.py`)

**Providers:** OpenAI, Anthropic, Gemini, DeepSeek, OpenRouter, Ollama

```python
await check_llm_health(config)     # 30s timeout
await complete(prompt, ...)        # 120s base, adaptive and remaining-budget capped
await complete_json(prompt, ...)   # 180s base, schema-aware bounded recovery
```

**Key Features:**

- API keys passed directly (avoids os.environ race conditions)
- Auto JSON mode for supported providers
- Default 2 content retries; increasing supported sampling values (0.1→0.3→0.5), with caller-specific retry counts
- Separate explicit transport policy; cancellation propagates
- One operation-wide deadline includes preloads, retries and persistence; [limits](ai-operation-budgets.md)
- Bracket-matching JSON extraction

## Services

### Parser (`services/parser.py`)

```python
await parse_document(content, filename) → str  # PDF/DOC/DOCX → Markdown, .tex → source
await parse_resume_to_json(markdown) → dict    # LLM call + date/link restoration
```

A PDF's hyperlinks are not in its text stream, so `_extract_pdf_links` reads
each page's `/Annots` array and `format_links_block` appends the result to the
extracted text as a `## Links extracted from the PDF file` block; after the LLM
answers, `restore_links_from_markdown` re-attaches anything it dropped. A
`.tex` upload skips MarkItDown entirely (`_extract_tex_source`) and is never
handed to the TeX engine. See the
[upload validation and resource policy](backend-guide.md#upload-validation-and-resource-policy).

### Improver (`services/improver.py`)

```python
await extract_job_keywords(job_desc) → dict    # LLM call
await improve_resume(original, job, keywords)  # LLM call
```

### Cover Letter (`services/cover_letter.py`)

```python
await generate_cover_letter(resume, job) → str    # LLM call
await generate_outreach_message(resume, job) → str # LLM call
```

## PDF Rendering (`pdf.py`)

Uses Playwright headless Chromium:

```python
await render_resume_pdf(url, page_size, selector=".resume-print")
```

**Critical:** CSS must whitelist print classes in `globals.css`:

```css
@media print {
  body * {
    visibility: hidden !important;
  }
  .resume-print,
  .resume-print * {
    visibility: visible !important;
  }
}
```

## Configuration

```bash
LLM_PROVIDER=openai|anthropic|gemini|deepseek|openrouter|ollama
LLM_MODEL=gpt-5-nano-2025-08-07
LLM_API_KEY=sk-...
FRONTEND_BASE_URL=http://localhost:3030
```

Non-secret config (provider/model/base/features) stored in `data/config.json`, takes
precedence over env vars. **API keys are never written to `config.json`** — they live
encrypted in the SQLite `api_keys` table (per-provider) and are injected into the config
dict only at read time. Set them via `POST /config/api-keys`; `PUT /config/llm-api-key` no
longer persists a key.

## Error Handling

Log detailed errors server-side, return generic messages to clients:

```python
except Exception as e:
    logger.error(f"Failed: {e}")
    raise HTTPException(500, "Operation failed. Please try again.")
```
