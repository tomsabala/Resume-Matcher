# Frontend API Client

> API client layer for Resume Matcher frontend.

## Base Client (`lib/api/client.ts`)

```typescript
export const API_URL: string;   // NEXT_PUBLIC_API_URL, default '/'
export const API_BASE: string;  // `${API_URL}api/v1`; a '/'-relative base is
                                // rewritten to the internal origin on the server
export const DEFAULT_TIMEOUT_MS: number; // 240_000, matching the backend deadline

export function setActiveWorkspaceId(workspaceId: string | null): void;
export async function apiFetch(endpoint: string, options?: RequestInit, timeoutMs?: number);
export async function apiPost<T>(endpoint: string, body: T, timeoutMs?: number);
export async function apiPatch<T>(endpoint: string, body: T);
export async function apiPut<T>(endpoint: string, body: T);
export async function apiDelete(endpoint: string);
export function getUploadUrl(): string;
```

Every request carries the active workspace as `X-Workspace-Id`; unset or
unknown resolves to the backend's default workspace.

## Resume Operations (`lib/api/resume.ts`)

```typescript
// Job descriptions
uploadJobDescriptions(descriptions: string[], resumeId: string) → job_id

// Resume tailoring (all three return ImprovedResult = ImproveResumeResponse['data'])
previewImproveResume(resumeId: string, jobId: string, promptId?: string) → ImprovedResult
confirmImproveResume(payload: ImproveResumeConfirmRequest) → ImprovedResult
improveResume(resumeId: string, jobId: string, promptId?: string) → ImprovedResult  // legacy one-shot

// CRUD
fetchResume(resumeId: string) → ResumeDetail
fetchResumeList(includeMaster?: boolean) → ResumeListItem[]
updateResume(resumeId: string, resumeData: ResumeDocument) → ResumeDetail
deleteResume(resumeId: string) → void
setMasterResume(resumeId: string) → { resume_id, is_master, previous_master_id }
saveResumeTemplateSettings(resumeId: string, settings: TemplateSettings) → TemplateSettings

// PDF
downloadResumePdf(resumeId: string, settings?: TemplateSettings) → Blob
downloadCoverLetterPdf(resumeId: string, pageSize?: string) → Blob

// Content updates
updateCoverLetter(resumeId: string, content: string) → void
updateOutreachMessage(resumeId: string, content: string) → void
renameResume(resumeId: string, title: string) → void

// On-demand generated content
generateCoverLetter(resumeId: string) → string
generateOutreachMessage(resumeId: string) → string
generateInterviewPrep(resumeId: string) → InterviewPrepData
```

## The Resume Document

Every endpoint that carries structured resume content carries the same object:
`ResumeDocument` (`apps/frontend/lib/types/document.ts`, mirroring
`apps/backend/app/schemas/document.py`). There is no separate request shape.

```jsonc
{
  "schemaVersion": 2,
  "header": {
    "name": "…",
    "headline": "…",
    "contacts": [{ "id": "…", "kind": "email", "label": "", "value": "…", "url": "" }]
  },
  "sections": [
    {
      "id": "…",
      "key": "experience",        // slug, unique per document; used in change paths
      "heading": "Experience",    // user-authored, free text
      "headingI18nKey": "resume.sections.experience", // null on user-created sections
      "kind": "entries",          // text | entries | tags | groups
      "visible": true,
      "column": "main",           // main | side (two-column templates partition on this)
      "text": "",
      "entries": [
        {
          "id": "…",              // stable for the entry's life
          "title": "Senior Engineer",
          "subtitle": "Acme",
          "meta": "Berlin",
          "period": "2023 -- May 2026",
          "links": [{ "kind": "github", "url": "…" }],
          "summary": "Owned the ingest tier.",
          "bullets": [{ "text": "Cut p99 by 40%", "style": "bullet" }]
        }
      ],
      "tags": [],
      "groups": []
    }
  ]
}
```

Contract notes that matter on the wire:

- **Order is list order.** `sections` is the display order; there is no order field.
- **`extra="forbid"`.** An unknown field is a `422`, never silently dropped.
  Round-trip whatever you were given.
- **Only the field group matching `kind` is meaningful**; the others stay at
  their empty defaults.
- **The header is not a section.**
- A resume stored under schema version 1 is projected to this shape on read by
  `migrate_document`; nothing writes v1 shapes.

| Endpoint | Body | Response |
|---|---|---|
| `GET /resumes?resume_id=` | — | `{ request_id, data: { resume_id, raw_resume, processed_resume: ResumeDocument \| null, cover_letter, outreach_message, interview_prep, parent_id, title, is_master, template_settings: TemplateSettings \| null } }` |
| `PATCH /resumes/{id}` | a complete `ResumeDocument` | same shape as `GET /resumes` |
| `POST /resumes/improve/preview` | `{ resume_id, job_id, prompt_id? }` | `{ request_id, data: ImproveResumeData }` — `resume_preview` is a `ResumeDocument`, `resume_id` is `null` |
| `POST /resumes/improve/confirm` | `{ resume_id, job_id, preview_id, improved_data: ResumeDocument, improvements, accepted_paths? }` | `{ request_id, data: ImproveResumeData }` — `resume_id` is the persisted tailored resume |
| `PUT /resumes/{id}/template-settings` | a `TemplateSettings` object | the settings as stored (see below) |

`PATCH` takes the whole document, not a partial patch: send back the document
you loaded, with your edits applied. `improve/confirm` must forward the
`improved_data` it was given by the preview unchanged — the server re-validates
it against the recorded preview fingerprint.

`ImproveResumeData.diff` is a `DocumentDiff` — the structured comparison of the
source resume against this proposal, in exactly the shape `POST /diff` returns,
so one component renders every diff surface. It is `null` when the comparison
could not be made, and the response then carries a warning saying so.

`accepted_paths` on confirm is the partial-accept selection: `null` (or omitted)
accepts the whole proposal, an array takes only those diff-row paths. Selectable
paths are content leaves only — see
[document-diff.md](../features/document-diff.md#partial-accept).

## The master resume (`POST /resumes/{id}/master`)

| Endpoint | Body | Response |
|---|---|---|
| `POST /resumes/{id}/master` | — | `{ resume_id, is_master: true, previous_master_id: string \| null }` |

Workspace-scoped like every other write: the target must belong to the
`X-Workspace-Id` workspace (`SetMasterResumeResponse` in
`apps/backend/app/schemas/models.py`).

| Status | Meaning |
| ------ | ------- |
| `200` | promoted; `previous_master_id` names the resume that was demoted, and is `null` when the workspace had no master or the target already was it (the call is idempotent) |
| `404` | no such resume — **or** it belongs to another workspace |
| `409` | `processing_status` is not `ready`; a pending, processing or failed resume cannot become the master |

Exactly one resume per workspace carries `is_master`, enforced by the partial
unique index `ux_resumes_workspace_master`. The route goes through
`db.set_master_resume()`, which demotes the old master and promotes the target
**inside one transaction** (demotions flushed first), so the index never sees
two masters and a failure leaves the old master in place.

**The previous master is kept as an ordinary resume** — not deleted, not
archived. Only its flag changes: its document, version timeline, `.tex`
override, template settings, cover letter, outreach message, interview prep and
tracker links are all untouched. It reappears in `GET /resumes/list` (which
filters the master out unless `include_master=true`), and promoting it back is
this same call.

Any `ready` resume qualifies, **a tailored one included**, and `parent_id` is
deliberately *not* cleared: it records where the document came from and is what
gates the cover-letter, outreach, interview-prep and job-description routes, so
clearing it would silently disable those on the new master. The consequence
worth telling the user about is upstream of tailoring: `get_master_resume()` is
the baseline every later tailoring is verified against
(`app/routers/resumes.py` feeds it to the refiner and
`app/prompts/refinement.py` instructs the model to check every claim against
it), so promoting a tailored resume makes a job-biased document the
anti-hallucination reference for future tailoring.

`GET /resumes?resume_id=` returns `is_master`, and **that flag is the only
authoritative answer to "is this the master?"**. The browser's
`master_resume_id` localStorage key is a cache/fallback: a promotion in another
tab, workspace switch or another browser leaves it pointing at a resume that is
now an ordinary one.

## Template settings (`PUT /resumes/{id}/template-settings`)

The template and formatting choice belongs to the **resume**, not the browser,
so the builder, the viewer and both export routes render what the user picked
for that resume on any device. `GET /resumes?resume_id=` and
`PATCH /resumes/{id}` return it as `data.template_settings`.

**`null` means "no choice stored yet"** — not "the defaults". A client that
gets `null` keeps its own last-used settings instead of snapping the resume
back to the default template. A stored payload the server cannot validate (one
written by a newer client, say) is logged server-side and reported as `null`
for the same reason: an unreadable presentation blob must never fail the fetch.

The body is the frontend's `TemplateSettings`
(`apps/frontend/lib/types/template-settings.ts`, mirrored by
`apps/backend/app/schemas/template_settings.py`) stored verbatim — camelCase,
and `extra="forbid"` at every level, so an unknown field is a `422` rather than
a silent drop. A `200` returns the object exactly as stored.

```jsonc
{
  "settingsVersion": 2,        // level-vocabulary marker; absent = v1
  "template": "swiss-single",  // one of the nine template ids (see below)
  "pageSize": "A4",            // "A4" | "LETTER"
  "margins":  { "top": 10, "bottom": 10, "left": 10, "right": 10 },  // mm, 5-25 each
  "spacing":  { "section": 5, "item": 4, "lineHeight": 5, "bulletLeadIn": 4 },
                                                                     // steps, 1-9 each
  "fontSize": {
    "base": 3, "headerScale": 3,                                     // steps, 1-5
    "headerFont": "serif", "bodyFont": "sans-serif"                  // serif | sans-serif | mono
  },
  "compactMode": false,
  "showContactIcons": false,
  "accentColor": "blue"        // "blue" | "green" | "orange" | "red"
}
```

The four spacing axes take levels **1-9**, the two font axes **1-5** (the LaTeX
`extarticle`/`extsizes` ladder is 8/9/10/11/12pt with nothing below 8pt, so
those axes have no step to add downward); every value shown is that field's
default and out-of-range is a `422`. `settingsVersion` is `Literal[2]`, and a
stored payload **without** it is v1, whose spacing levels ran 1-5: v1 and v2
level numbers overlap, so the marker is the only thing that disambiguates the
payload. Reading a v1 payload upgrades it — `+2` on each spacing level, which
puts the old 1-5 on 3-7 with identical physical output, font levels and all
other fields untouched — in `_parse_template_settings`
(`apps/backend/app/routers/resumes.py`) and, client-side, in
`readTemplateSettings`
(`apps/frontend/lib/utils/template-settings-storage.ts`).

`template` is one of `swiss-single`, `swiss-two-column`, `modern`,
`modern-two-column`, `latex`, `clean`, `vivid` (the Chromium-rendered
`HTML_TEMPLATES`) or `tex-classic`, `tex-compact` (`TEX_TEMPLATES`, compiled by
the engine). Every field shown has that default, so a partial body validates
and the omitted fields are stored at their defaults — this is a `PUT`, not a
merge: what you send is what the resume carries afterwards.

| Status | Meaning |
| ------ | ------- |
| `200` | stored; the body is the settings as saved |
| `404` | unknown resume id |
| `422` | unknown field, number out of range, or a value outside an allowed set (e.g. an unrecognised `template` id) |

**Not versioned.** These settings are presentation, not content, so they never
reach `resume_versions`: restoring an older document does not revert how the
resume looks, and a `PATCH /resumes/{id}` leaves them untouched.

**Tailoring inherits them.** `POST /resumes/improve/confirm` and the one-shot
`POST /resumes/improve` copy the parent's `template_settings` onto the resume
they create (a `null` parent gives a `null` child), so a tailored resume opens
looking like the one it came from rather than resetting to a default.

## AI change paths

The tailoring LLM does not rewrite the resume; it returns a list of targeted
changes, each one a path plus an action
(`apps/backend/app/schemas/models.py::ResumeChange`):

```jsonc
{
  "path": "sections.experience.entries[0].bullets[1].text",
  "action": "replace",          // replace | append | reorder | add_skill
  "original": "Built APIs",     // verified against the live value before applying
  "value": "Built ingest APIs serving 1M req/day",
  "reason": "JD asks for high-throughput API experience"
}
```

A section is addressed **by key, not by position**: the `sections.<key>`
segment matches the list item whose `key` field equals the segment, so a user
reorder cannot retarget a different section.

Editable paths — the allowlist is *generated per document* by
`improver.build_allowed_paths` from the document's own sections and their kinds:

| `kind` | Editable paths |
|---|---|
| `text` | `sections.<key>.text` |
| `entries` | `sections.<key>.entries[i].summary`, `sections.<key>.entries[i].bullets`, `sections.<key>.entries[i].bullets[j].text` |
| `tags` | `sections.<key>.tags` |
| `groups` | `sections.<key>.groups[i].values` |

Because the allowlist is a function of the document, **a section the user
created is as editable as any other** — there is no fixed set of section names
to be absent from.

Never editable: `header.*` and `schemaVersion` (identity), and the fields `id`,
`key`, `kind`, `heading`, `headingI18nKey`, `visible`, `column`, `title`,
`subtitle`, `meta`, `period`, `links`, `label`, `style` (identity and
structure). A change targeting one of those is rejected, not clamped.

Action rules enforced by `apply_diffs`:

- `replace` — one text leaf only; a list-valued path is rejected.
- `append` — **bullet lists only** (a path ending in `.bullets`); appended as
  `{"text": …, "style": "bullet"}`.
- `add_skill` — the only way to add a short value to a `tags`/`groups` list, and
  it is gated on the verified skill-target plan.
- `reorder` — same items, new order; unverified new items are dropped and
  omitted originals are appended back.

Resume upload accepts matching PDF, DOC, DOCX or TEX filename/MIME pairs. One
extension maps to a *set* of acceptable MIME types — `.tex` arrives as
`text/x-tex`, `application/x-tex`, `text/plain` or `application/octet-stream`
depending on the OS — but extension and MIME must still agree, so `text/plain`
with a `.pdf` filename is rejected. The backend returns 400 for unsupported or
mismatched types (`Invalid file type: {type}. Allowed: PDF, DOC, DOCX, TEX` and
`Upload a valid PDF, DOC, DOCX, or TEX file.`), 413 for raw/expanded/extracted
size limits, and 422 for malformed or textless/scanned documents
(`Failed to parse document. Please upload a valid PDF, DOC, DOCX, or TEX
file.`). Upload and retry processing return 409 when a newer processing attempt
supersedes the request, or 404 when the resume is deleted while processing.

A `.tex` upload is read as source, never compiled: comments are stripped (`\%`
survives) and only the `\begin{document}`…`\end{document}` body is kept when
those markers are present. A PDF upload goes through MarkItDown, which reads
only the text stream, so its hyperlinks are recovered separately from each
page's `/Annots` array, appended to the extracted text as a
`## Links extracted from the PDF file` block, and re-attached after the LLM by
`restore_links_from_markdown`. Both land in the string the upload route stores
as the resume's `content`, which `POST /resumes/{id}/retry-processing` re-runs
the LLM on — links passed out of band would be lost on re-parse. See
[the upload/parse pipeline](../architecture/backend-guide.md#upload-validation-and-resource-policy)
and [PDF link recovery](../architecture/backend-guide.md#pdf-link-recovery).

## Preview and confirmation

Preview returns `data.preview_id` and `data.preview_expires_at`; confirmation forwards `preview_id` with the unchanged proposed resume. Successful retries return the same stored response without creating another resume. An active confirmation returns 409 with `Retry-After: 1`; stale or expired input snapshots require a new preview. See [the complete contract and transaction lifecycle](../features/preview-confirmation.md).

## Resume Wizard (`lib/api/resume-wizard.ts`)

```typescript
postResumeWizardTurn(payload: ResumeWizardTurnRequest) → ResumeWizardTurnResponse
finalizeResumeWizard(state: ResumeWizardState) → ResumeWizardFinalizeResponse
createInitialResumeWizardState() → ResumeWizardState
```

Backend endpoints:

- `POST /api/v1/resume-wizard/turn` — one adaptive turn. `action` is `start | answer | skip | back | review`. A turn targets `intro`, `contact`, `review`, or one section of the document as `section:<section_key>` (e.g. `section:military_service`) — the wizard has no built-in section enum, so a section the user added is a legitimate target. `answer`/`skip` run one AI call that updates `resume_data` (a full `ResumeDocument`), returns the next `current_question`, `inferred_skills`, and a strict boolean `is_complete` flag; `back`/`review`/`start` are deterministic (no LLM). The service validates the complete model envelope before advancing history or progress. Invalid envelopes return a recoverable `422` and leave the client state unchanged. Entries are merged back by their stable `Entry.id`, falling back to a `(title, subtitle, period)` signature when the model omits or invents one; a new entry is allocated a fresh id. Partial model echoes preserve entries they omit. Deterministic fallback questions and review copy use the configured content language. The full `ResumeWizardState` round-trips in the request and response.
- `POST /api/v1/resume-wizard/finalize` — creates the single master resume from the draft (`processing_status: "ready"`), or `409` if a master already exists. Creation is not the only way a workspace gets its master: an existing `ready` resume can be promoted later with [`POST /resumes/{id}/master`](#the-master-resume-post-resumesidmaster).

The wizard is an AI-led, one-question-at-a-time flow that builds a general master resume; it does not require a job description and does not replace the upload parser. Question and content text are produced in the configured **content language**; static UI chrome uses the `resumeWizard.*` i18n keys.

## AI enrichment and regenerate (`lib/api/enrichment.ts`)

```typescript
analyzeResume(resumeId: string) → AnalysisResponse
generateEnhancements(resumeId: string, answers: AnswerInput[]) → EnhancementPreview
applyEnhancements(resumeId: string, enhancements: EnhancedDescription[]) → { message, updated_items }
regenerateItems(request: RegenerateRequest) → RegenerateResponse
applyRegeneratedItems(resumeId: string, items: RegeneratedItem[]) → { message, updated_items }
```

### Item ids

Both flows address a piece of the document with an `item_id` plus an
`item_type`. **An item id is built from stable ids, never from a position or a
heading:**

| `item_type` | `item_id` | Addresses |
|---|---|---|
| `entry` | `<section_key>:<entry_id>` | one entry of an `entries` section — e.g. `experience:3f1c9ab24d7e4c0fa1b2c3d4e5f60718` |
| `values` | `<section_key>:#tags` | the flat value list of a `tags` section — e.g. `languages:#tags` |
| `values` | `<section_key>:#group:<index>` | one group's `values` in a `groups` section — e.g. `skills:#group:0` |

`section_key` is `Section.key` and `entry_id` is `Entry.id`, both copied
verbatim from the document. Entry ids are stable for the entry's life, so a
reorder between analysis, preview and apply cannot retarget a different entry.
An id the server cannot resolve is reported as an item error and discarded —
it is never applied to a best-guess target. The prompts instruct the model to
copy ids out of the JSON and never to derive one from a heading or an array
position.

Items also carry `section_heading`, a **display-only** field holding the
owning section's heading (falling back to its key). The UI labels an item with
the user's own section name; `item_type` is what the code dispatches on, so
"Experience" and "Projects" are not categories the backend knows.

A `RegeneratedItem` carries `item_id`, `item_type`, `title`, `subtitle`,
`original_content`, `new_content`, a free-text `diff_summary` the model wrote,
and **`rows: DiffRow[]`** — the server-computed comparison of
`original_content` against `new_content`, word-level spans included. The rows
are the same `DiffRow`s `POST /diff` returns, so the regenerate preview renders
through the shared diff component and the client never re-derives a comparison.
Send the item back to `apply-regenerated` as received.

See [enrichment.md](../features/enrichment.md).

## Version History (`lib/api/versions.ts`)

```typescript
listVersions(resumeId: string, cursor?: string) → VersionListResponse
fetchVersion(versionId: string) → VersionDetail        // includes the full ResumeDocument
updateVersion(versionId: string, payload) → VersionDetail   // label / pin
deleteVersion(versionId: string) → void
restoreVersion(resumeId: string, versionId: string) → VersionSummary
```

History is append-only: a restore writes the chosen version forward as a new
head rather than rewinding, so the restore is itself on the timeline. A version
carries its `origin` (`import | manual | ai_tailor | ai_enrich | wizard |
restore | tex_edit`) — every AI write goes through this funnel, which is why an
enrichment or tailoring the user dislikes is recoverable.

## Document Diff (`POST /diff`)

Each side of a comparison is a ref — exactly one of `{ resume_id }` or
`{ version_id }`, otherwise `422` — so resume-vs-resume, version-vs-version and
resume-vs-version are one endpoint:

```jsonc
{
  "base": { "resume_id": "…" },
  "head": { "version_id": "…" },
  "mode": "document",   // "document" (section/entry/row rows) | "tex" (LaTeX line diff)
  "context": 2          // 0-20; unchanged rows kept around each change, 0 = changes only
}
```

`mode: "document"` returns a `DocumentDiff`: `{ stats, header: DiffRow[],
sections: SectionDiff[] }`, grouped by section and ordered as the head document
reads. `mode: "tex"` returns `{ rows: DiffRow[] }`, a line diff over the two
sides' LaTeX sources. A resume ref resolves `processed_data`; a version ref
resolves that timeline entry's document; both are projected through
`migrate_document`.

| Outcome | HTTP |
|---|---|
| A ref naming both `resume_id` and `version_id`, or neither | 422 |
| Unknown `resume_id` / `version_id` | 404 |
| Either ref outside the active workspace (`X-Workspace-Id`) | 403 |

Diff rows are keyed by the same section/entry path grammar as the change paths
above, which is what makes a row individually acceptable on confirm. Row kinds,
statuses, spans and the pairing rules behind them:
[document-diff.md](../features/document-diff.md).

## LaTeX Export (`lib/api/tex.ts`)

```typescript
getTexCapabilities() → TexCapabilities          // GET  /resumes/tex/capabilities
getTexSource(resumeId, { template?, regenerate?, format? }) → TexSource
                                                // GET  /resumes/{id}/tex
saveTexSource(resumeId, source) → TexSource     // PUT  /resumes/{id}/tex
clearTexSource(resumeId, template?, format?) → TexSource // DELETE /resumes/{id}/tex
downloadTexSource(resumeId, template?, format?) → Blob   // GET  /resumes/{id}/tex/source
compileTexPdf(resumeId, template?, format?) → Blob       // GET  /resumes/{id}/tex/pdf
texFormatParams(format?) → URLSearchParams      // the formatting query the engine reads
```

```typescript
interface TexCapabilities {
  engine: string | null;   // bare binary name; null = cannot compile here
  can_compile: boolean;
  templates: string[];     // 'tex-classic' | 'tex-compact'
}

interface TexSource {
  resume_id: string;
  source: string;
  is_override: boolean;    // true = the user's own .tex, not generated
  template: string;        // 'custom' on a PUT response
  engine: string | null;   // travels with the source, so the UI needs no second call
}
```

`template` defaults to `tex-classic` on every route that renders.
`regenerate=true` returns freshly generated source for one read without
clearing a stored override. `PUT` bodies are `{ source }`, 1–400,000 chars.
`format` is a `TexFormatSettings` (a `TemplateSettings` narrowed to
`pageSize`, `margins`, `spacing`, `fontSize`, `compactMode`) and becomes the
query the LaTeX engine reads — same parameter names and bounds as the Chromium
`/pdf` route (spacing axes 1–9, font axes 1–5), plus the LaTeX-only
`bulletLeadIn`. Omitted, only `pageSize=A4` is sent and each template keeps its
reference geometry.

| Status | Meaning |
| ------ | ------- |
| `400` | unknown `template` id; the detail lists the valid ones |
| `404` | unknown resume id |
| `422` | a formatting parameter outside its range (margins 5–25mm, spacing levels 1–9, font levels 1–5), or `/tex/pdf` — the engine rejected the source. The compile detail is `{ message, log }`, surfaced by the client as `TexCompileError` with the engine log attached |
| `503` | `/tex/pdf` — no engine on this host, raised as `TexUnavailableError`. Distinct from a `500`: the request is valid, the capability is absent, and the caller should offer the `.tex` download instead |

A `PUT` or `DELETE` writes a version checkpoint (`origin: "tex_edit"`,
`tex_source_mode: "edited" | "generated"`), so the timeline above shows LaTeX
edits and a reset never loses one. Details:
[latex-export.md](../features/latex-export.md).

## Workspaces (`lib/api/workspaces.ts`)

```typescript
listWorkspaces() → Workspace[]
createWorkspace(payload: WorkspaceCreate) → Workspace
updateWorkspace(workspaceId: string, payload: WorkspaceUpdate) → Workspace
deleteWorkspace(workspaceId: string) → void
```

A workspace is a named owner profile, not a tenant — there is no auth. It scopes
resumes, jobs and tracker cards; exactly one row is the default. Requests select
one with `X-Workspace-Id`, and a missing **or unknown** id falls back to the
default workspace (the Playwright print route sends no app headers, and a stored
browser id can outlive a deleted workspace).

Both mutations have a UI: the header switcher's per-row pencil opens
`components/common/workspace-manage-dialog.tsx` (rename, content language,
promote to default, delete). Deleting the default workspace or the only
workspace is refused server-side with `409` and the dialog shows that message
verbatim — the rule has one owner. Deleting the active workspace makes the
remaining default (or first) workspace active.

Resumes are managed from the dashboard cards: the pencil calls
`renameResume(id, title)` (`PATCH /resumes/{id}/title`, dashboard label only —
the document is untouched) and the bin calls `deleteResume(id)`. Deleting the
master clears the stored `master_resume_id` and the dashboard falls back to its
upload card; tailored resumes survive. The same manage surface calls
`setMasterResume(id)` to promote a resume; that demotes the current master into
an ordinary card instead of removing it — see
[the master resume](#the-master-resume-post-resumesidmaster).

## Application Tracker (`lib/api/tracker.ts`)

Tracker patches distinguish omission from explicit null: omitted `status` keeps the current column, while `status: null` returns 422. Nullable text/date fields remain clearable. Each move from `saved` to a non-saved column stamps `applied_at` if it has no date; explicit dates (including an explicitly cleared date in the same patch) are preserved. Bulk moves use the same rule. Moving back to `saved` retains any existing date; applying again fills a missing date. Moves between non-saved columns leave cleared dates empty.

Create, move, and delete operations reserve the SQLite writer before allocating or renumbering column positions. This keeps positions contiguous across concurrent single/bulk operations and separate database connections; the resume/job pair uniqueness constraint remains independent.

```typescript
// Kanban board (7 status columns: saved | applied | no_response |
// response | interview | accepted | rejected)
listApplications() → ApplicationListResponse        // { columns: Record<status, Application[]> }
createApplication(payload: ManualApplicationCreate) → Application   // manual add from a pasted JD
getApplicationDetail(id: string) → ApplicationDetail               // embedded JD + applied resume (resume null if deleted)
updateApplication(id: string, payload: ApplicationUpdate) → Application   // status/position/notes/company/role/applied_at

// Bulk
bulkUpdateStatus(applicationIds: string[], status: ApplicationStatus) → ApplicationActionResponse
deleteApplication(id: string) → void
bulkDeleteApplications(applicationIds: string[]) → ApplicationActionResponse
```

## Config Operations (`lib/api/config.ts`)

```typescript
fetchLlmConfig() → LLMConfig
updateLlmConfig(config: LLMConfigUpdate) → LLMConfig
testLlmConnection() → LLMHealthCheck
fetchSystemStatus() → SystemStatus

// Per-provider API keys (encrypted server-side; switching the active
// provider no longer wipes another provider's key — responses always masked)
fetchApiKeyStatus() → ApiKeyStatusResponse           // { providers: [{ provider, configured, masked_key }] }
updateApiKeys(keys: ApiKeysUpdateRequest) → ApiKeysUpdateResponse
deleteApiKey(provider: ApiKeyProvider) → void
clearAllApiKeys() → void

// Feature flags
fetchFeatureConfig() → FeatureConfig
updateFeatureConfig(config: FeatureConfigUpdate) → FeatureConfig

// Language
fetchLanguageConfig() → LanguageConfig
updateLanguageConfig(language: string) → LanguageConfig
```

> `updateLlmApiKey` (`PUT /config/llm-api-key`) no longer persists a key — keys are managed per-provider via the encrypted `/config/api-keys` endpoints above.

## AI diagnostics (`lib/api/diagnostics.ts`)

```typescript
fetchAIFailures() → AIFailure[]        // GET    /diagnostics/ai-failures  → payload.failures
dismissAIFailures() → number           // DELETE /diagnostics/ai-failures  → payload.dismissed
```

Both endpoints answer with the same envelope, so a dismiss needs no second
request to learn the new (empty) state:

```typescript
// GET    → { failures: [...], dismissed: 0 }
// DELETE → { failures: [],    dismissed: 3 }   // how many were dropped
interface AIFailure {
  id: string;                  // uuid4, per record
  at: string;                  // ISO-8601 UTC, second precision
  operation: string;           // the call's schema: 'resume', 'diff', 'enrichment', 'keywords', 'interview_prep'
  kind: AIFailureKind;
  detail: string;              // operator-facing message, capped at 300 characters
  model?: string | null;       // resolved model id, when the call got that far
  provider?: string | null;
  attempts?: number | null;    // attempts made before giving up
  max_tokens?: number | null;  // output budget in force on the last attempt
}
```

`failures` is newest first. A non-2xx response makes both client functions
throw; the dashboard panel swallows that (see
[Dashboard](../architecture/frontend-workflow.md#1-dashboard-dashboard)).

`kind` is a closed vocabulary — `'truncated' | 'malformed' | 'empty' | 'invalid' | 'provider'`:

| `kind` | What went wrong | What the user can do |
| --- | --- | --- |
| `truncated` | The model hit its output budget mid-answer | Shorten the input or pick a model with a larger output limit |
| `malformed` | The answer arrived but is not parseable JSON | Retry; a weaker model is the usual cause |
| `empty` | The provider returned no answer at all | Retry; check the provider's status |
| `invalid` | Parseable JSON that validation rejected | Retry; the model ignored the schema |
| `provider` | Upstream/transport error (auth, rate limit, network) | Check the API key, quota and connectivity |

Render an unrecognised `kind` as `provider` rather than dropping the row.

**The records carry no prompt, resume text, job text or model output** — only
the shape of the failure (operation, category, model, provider, attempts,
budget) plus the capped `detail`. Everything in the payload is safe to show in
the UI.

Only **terminal** failures are recorded: a retry that recovered leaves nothing
behind. The tail is in-process, bounded to the 20 most recent records, and
lost on a backend restart — a diagnostic tail, not an audit log. So an empty
`failures` array means "nothing recent", never "nothing ever".

## Provider Info

```typescript
export const PROVIDER_INFO = {
  openai: {
    name: 'OpenAI',
    defaultModel: 'gpt-5-nano-2025-08-07',
    requiresKey: true,
  },
  anthropic: {
    name: 'Anthropic',
    defaultModel: 'claude-haiku-4-5-20251001',
    requiresKey: true,
  },
  openrouter: {
    name: 'OpenRouter',
    defaultModel: 'deepseek/deepseek-chat',
    requiresKey: true,
  },
  gemini: {
    name: 'Google Gemini',
    defaultModel: 'gemini-3-flash-preview',
    requiresKey: true,
  },
  deepseek: {
    name: 'DeepSeek',
    defaultModel: 'deepseek-chat',
    requiresKey: true,
  },
  ollama: {
    name: 'Ollama (Local)',
    defaultModel: 'gemma3:4b',
    requiresKey: false,
  },
};
```

## Usage

```typescript
import { fetchResume, API_BASE, PROVIDER_INFO } from '@/lib/api';
```

Legacy `.doc` files pass compound-file header validation, but the bundled MarkItDown DOCX converter does not guarantee binary Word conversion. Convert legacy Word documents to PDF or DOCX for reliable upload. A LaTeX-built CV is best uploaded as `.tex`, which keeps the links and bold that a PDF's text stream drops.

## Refinement and monitoring statistics

`refinement_stats.passes_attempted` counts attempted refinement stages. `passes_completed` counts stages that changed content; a failed or unchanged keyword injection no longer counts as completed. `keywords_eligible` counts missing source-supported candidates before injection, while `keywords_injected` counts those actually present in the final result. `alignment_violations_fixed` counts critical violations resolved by the local correction pass. Preview and legacy improve responses share the same statistics model and conversion.

Preview error logs identify the stage actually running, including cancellation and timeout. Client messages keep the existing generic error boundary. The opt-in monitor records monotonic elapsed milliseconds and explicit skipped/error/cancelled outcomes; see its [run and isolation contract](../../../apps/backend/e2e_monitor/README.md). These counters and heuristic scores do not claim commercial ATS accuracy.
