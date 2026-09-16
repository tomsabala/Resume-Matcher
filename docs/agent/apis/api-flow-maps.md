# API Flow Maps

> Request/response flows for all Resume Matcher endpoints.

## Resume Upload

```
POST /api/v1/resumes/upload
├── Validate file (PDF/DOC/DOCX/TEX, ≤4MB; extension must match declared MIME)
├── parse_document() → Markdown (`.tex` → LaTeX source; PDF links appended)
├── db.create_resume(status="processing")
├── parse_resume_to_json() → LLM
│   ├── restore_dates_from_markdown() + restore_links_from_markdown()
│   ├── Success: status="ready"
│   └── Failure: status="failed"
└── Return {resume_id}
```

## Resume Improvement

```
POST /api/v1/resumes/improve
├── Fetch resume + job from DB
├── extract_job_keywords() → LLM
├── improve_resume() → LLM
├── [If enabled] generate_cover_letter() → LLM
├── [If enabled] generate_outreach_message() → LLM
├── [If enabled] generate_interview_prep() → LLM
├── db.create_tailored_resume()       # copies the parent's template_settings
├── db.create_improvement()
└── Return {data, cover_letter, outreach_message, interview_prep}
```

The tailored resume inherits how its parent looks: both this legacy path and
`POST /resumes/improve/confirm` write the parent's `template_settings` onto the
new row, so a tailored copy is never re-themed to a default.

## Interview Prep Generation

```
POST /api/v1/resumes/{id}/generate-interview-prep
├── Require tailored resume (parent_id)
├── Fetch improvement record and associated job description
├── Require processed resume data
├── generate_interview_prep() → LLM JSON
├── Validate InterviewPrepData
├── Save resumes.interview_prep as serialized JSON TEXT
└── Return {interview_prep, message}
```

## PDF Generation

```
GET /api/v1/resumes/{id}/pdf
├── Fetch resume from DB
├── Build URL: {frontend}/print/resumes/{id}?{params}
├── Playwright render (wait for .resume-print)
└── Return PDF bytes
```

## Health Check

```
GET /api/v1/health
└── Return {status: "healthy"}        # pure liveness — does NOT call the LLM
```

## System Status

```
GET /api/v1/status                    # each check isolated → 200 (partial/degraded), never 500
├── try: get_llm_config()
│   ├── llm_configured = api_key set OR provider ∈ {ollama, openai_compatible}
│   └── check_llm_health() → llm_healthy   # failure here degrades only this field
├── try: db.get_stats()                     # failure → empty stats, still 200
└── Return {status, llm_configured, llm_healthy, has_master_resume, database_stats}
```

## AI Failure Diagnostics

```
complete_json(...)                     # every structured LLM call goes through it
└── except: record_ai_failure(...)     # TERMINAL failure only — a recovered retry records nothing
    └── app/ai_events.py deque         # in-process, newest-first, max 20, dropped on restart
                                       #   operation/kind/detail(≤300 chars)/model/provider/
                                       #   attempts/max_tokens — never prompt, resume or output

GET /api/v1/diagnostics/ai-failures    # dashboard panel, polled every 30 s
└── Return {failures: [...], dismissed: 0}     # kind ∈ truncated|malformed|empty|invalid|provider

DELETE /api/v1/diagnostics/ai-failures # the panel's Dismiss button
└── Return {failures: [], dismissed: N}        # N = how many were dropped
```

## Configuration Update

```
PUT /api/v1/config/llm-api-key
├── _load_config()
├── Merge new NON-SECRET values (provider/model/base/...)
├── (no longer persists any key — keys go through /config/api-keys)
├── _save_config()
└── Return masked config
```

## API Keys (per-provider, encrypted)

```
GET /api/v1/config/api-keys
└── Return {providers: [{provider, configured, masked_key}]}   # always masked

POST /api/v1/config/api-keys
├── For each provided provider key:
│   └── Fernet-encrypt → upsert into SQLite `api_keys` table   # other providers' keys untouched
└── Return {message, updated_providers}

DELETE /api/v1/config/api-keys/{provider}      # remove one provider's key
DELETE /api/v1/config/api-keys?confirm=...     # clear all keys
```

## Job Upload

```
POST /api/v1/jobs/upload
├── For each description:
│   └── db.create_job()
└── Return {job_id[]}
```

## Resume Operations

| Endpoint | Flow |
|----------|------|
| `GET /resumes?id=` | db.get_resume() — `data.template_settings` is the resume's own template/formatting choice, `null` when it has none yet |
| `GET /resumes/list` | db.list_resumes() |
| `PATCH /resumes/{id}` | db.update_resume() |
| `DELETE /resumes/{id}` | db.delete_resume() |
| `PUT /resumes/{id}/template-settings` | db.update_resume({template_settings}) — presentation only, so no version checkpoint |

## Application Tracker

```
GET /api/v1/applications
├── db.list_applications()
└── Return {columns}        # grouped by the 7 status keys (all present):
                            #   saved/applied/no_response/response/interview/accepted/rejected

POST /api/v1/applications   # manual add from a pasted JD
├── db.create_job(jd)
├── [If company/role missing] extract_job_keywords() → LLM   # one best-effort call
├── db.create_application(status default "applied")          # dedupes on (job_id, resume_id)
└── Return Application

GET /api/v1/applications/{id}
├── db.get_application() + embed job_content + applied resume
└── Return {..., job_content, resume}    # resume: null if it was deleted
```

| Endpoint | Flow |
|----------|------|
| `PATCH /applications/{id}` | db.update_application() — status/position/notes/company/role/applied_at; server renumbers `position` |
| `PATCH /applications/bulk` | db.bulk_update_status() — move many cards to one column |
| `DELETE /applications/{id}` | db.delete_application() |
| `POST /applications/bulk-delete` | db.bulk_delete_applications() |

> **Auto-create:** `POST /resumes/improve/confirm` (and legacy `POST /resumes/improve`) create an `applied` card after persisting the tailored resume — best-effort (a tracker failure never breaks tailoring); company/role reuse the cached keyword extraction, so no extra LLM call.
