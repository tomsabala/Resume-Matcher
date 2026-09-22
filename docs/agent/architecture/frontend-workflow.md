# Frontend Workflow

> User flows and state management for Resume Matcher.

## Core User Flow

```
Dashboard → Upload Master Resume → Tailor for Job → View/Edit → Download PDF
```

## Pages

### 1. Dashboard (`/dashboard`)

- **No master:** "Initialize Master Resume" card
- **Has master:** "Master Resume" card + tailored tiles. Any `ready` card can be
  promoted with `setMasterResume(id)` (`POST /resumes/{id}/master`); the old
  master is demoted to an ordinary tile, keeping its document, versions and
  tracker links, and can be promoted back
  ([contract](../apis/front-end-apis.md#the-master-resume-post-resumesidmaster))
- **Create:** "+" card opens `/tailor`
- Auto-refreshes on window focus
- List and status results are applied only while their request and master identity are current. Late responses cannot replace newer cards or clear a different master.
- Pending/processing master status is polled serially with a 3–30 second backoff, for at most 12 polls. Hidden tabs skip polling. Polling stops on ready/failed, missing master, or unmount; focus refresh and Retry provide recovery after a failure.
- Selecting exactly two resume cards enables **Compare**, which navigates to
  `/compare?base=resume:<a>&head=resume:<b>`.
- **AI failures:** `components/dashboard/ai-failure-panel.tsx` sits at the top
  of the page and states *why* the last AI operations failed instead of a
  generic "please try again". One row per failure — category (`truncated`,
  `malformed`, `empty`, `invalid`, `provider`), the operation, local time, the
  capped detail message, and the model, output budget and attempt count when
  known; a `truncated` row adds the actionable hint (shorten the input or raise
  the model's output limit). It renders `null` when there are no failures,
  re-reads `GET /diagnostics/ai-failures` every 30 s (and on a failed master
  status) so a failure appears without a reload, and **Dismiss** clears
  server-side via `DELETE /diagnostics/ai-failures`. Its own fetch and dismiss
  errors are swallowed — diagnostics must never break the dashboard they
  annotate. The tail is bounded to 20 records, carries no prompt, resume or
  model output, and is lost on a backend restart (see the
  [client contract](../apis/front-end-apis.md#ai-diagnostics-libapidiagnosticsts)).

### 2. Resume Viewer (`/resumes/[id]`)

- Read-only display at 250mm width
- Actions: Back, Edit, Download PDF, Delete, and — on a `ready` resume that is
  not already the master — **Set as master**, gated on `data.is_master` from the
  fetch rather than on the cached `master_resume_id`
- Renders and exports with the resume's own `template_settings` (see
  [Template Settings](#template-settings)), not with the defaults
- Delete shows confirmation + success dialogs

### 3. Tailor (`/tailor`)

- Job description textarea (min 50 chars)
- Process: Upload JD → Improve → Redirect to viewer

### 4. Builder (`/builder`)

- **Left panel:** Editor (forms + formatting)
- **Right panel:** WYSIWYG preview
- **Tabs:** Resume | Cover Letter | Outreach
- An editor instance belongs to one URL resume ID. Changing the ID remounts
  editor state, including its save queue, dirty/version state and Reset baseline.
  Requests already sent may finish for their original ID; their abandoned editor
  cannot update state, remove drafts, or dispatch queued saves after unmount.
- With an ID, only a usable processed resume or raw JSON resume establishes an
  editable server baseline. A failed GET, malformed response, or pending/failed
  processing state blocks Save/autosave and retains the local draft. Context from
  another resume never substitutes for the unavailable server snapshot.
- Once that baseline loads, a differing scoped draft requires explicit restore
  confirmation before autosave can persist it. Without an ID, context, a new-resume
  local draft and defaults remain the fallbacks; server saves require an ID.

### 5. Settings (`/settings`)

- System status (cached)
- LLM configuration (6 providers)
- Last fetched indicator + manual refresh

### 6. Compare (`/compare`)

- Reads `?base=` and `?head=`; each is a `resume:<id>` or `version:<id>` token,
  so a comparison is a linkable thing rather than modal state. A token that
  does not parse is reported as an invalid link and no request is made.
- Fetches `POST /diff` through `lib/api/diff.ts` and renders `DiffView`
  read-only (no accept checkboxes).
- Reached from the dashboard's two-resume selection and from the **Compare**
  button on a version-timeline row (`base=version:<id>&head=resume:<id>` —
  "what changed since this point").

## Pagination Rules

- Sections CAN span pages
- Individual items stay together
- Pages ≥50% full before break
- Headers never orphaned

## Phone Layout (below `lg`)

Below Tailwind's `lg` (1024 px) the app is a different information architecture,
not a narrowed desktop. Desktop at `lg` and above is unchanged.

| Piece | File | Notes |
| --- | --- | --- |
| Breakpoint check | `hooks/use-is-mobile.ts` | `useIsMobile()` over `matchMedia('(max-width: 1023.98px)')`. `false` during SSR and the first hydration frame, so **every runtime branch is also CSS-gated** (`lg:hidden` / `hidden lg:block`) — that frame paints nothing rather than the desktop tree |
| Tab bar | `components/common/bottom-nav.tsx` | Four slots (Resumes / Tracker / ⊕ Create / Settings), `sticky bottom-0` flex sibling of `<main>`. Shown on `/dashboard`, `/tracker`, `/settings`; absent on the detail routes and `/print*`. Never `fixed` — sticky occupies flow space, so no page needs bottom padding |
| Top bar | `components/common/app-header.tsx` | Back chevron on detail routes, route title, workspace switcher |
| Thumb-zone actions | `components/common/mobile-action-bar.tsx` | `aboveNav` on tab routes (`bottom-[var(--mobile-nav-h)]`), plain `bottom-0` + safe-area padding on detail routes |
| Sheets | `components/ui/dialog.tsx`, `components/ui/action-sheet.tsx` | Below `sm` every `DialogContent` is a bottom sheet (grab handle, `max-h-[92dvh]`). `ActionSheet` replaces crowded icon clusters |
| Rows | `components/ui/list-row.tsx` | Replaces aspect-square cards. `trailing` is a **sibling** of the tappable area, never a child — a button inside a button is a hydration error |
| Switches | `components/ui/segmented.tsx` | Equal-width 2–3 way switch (builder EDIT/PREVIEW, READ/PAGE, diff unified/split) |

Per-surface shape: the dashboard is a list with a per-row `⋯` sheet (and a
pick-a-second-row compare mode instead of checkboxes); the tracker shows one
stage at a time with the stage chips as a filter and a "Move to…" sheet instead
of cross-stage drag; the builder is a two-level drill-down (section index →
one section's fields, no drag gutter) with formatting in a sheet; settings is an
index of five rows that drills into one section. The builder preview defaults to
`components/preview/reading-preview.tsx` (a reflowed reading view that reuses the
`@media screen and (max-width: 639px)` rules scoped to `:global(.resume-print)`),
with the exact scaled A4 page one tap away. `--mobile-nav-h` in `globals.css`
is the bar height including the device safe area.

## State Management

### localStorage

| Key | Purpose |
| --- | --- |
| `master_resume_id` | Master resume UUID — a **cache/fallback only**. The server owns master-ness: `GET /resumes?resume_id=` returns `is_master`, and a promotion in another tab or browser leaves this key naming a demoted resume |
| `resume_builder_draft:<resumeId>` / `resume_builder_draft:new` | Resume-scoped recovery draft; a failed write is shown as unavailable and never described as saved |
| `resume_builder_settings` | Last-used template/formatting settings — the default for a resume that has none of its own, not the choice itself |
| `resume_wizard_draft` | Versioned wizard state; nested resume/history values are normalized before restoration |

### Template Settings

The template and formatting choice lives on the resume
(`Resume.template_settings`), so it survives a reload and follows the resume
to another browser.

| Step | Where |
| --- | --- |
| Read on load | `components/builder/resume-builder.tsx` → `adoptTemplateSettings(data.template_settings)`; a `null` keeps the browser's last-used settings, so no existing resume resets to `swiss-single` |
| Write on change | `saveResumeTemplateSettings(resumeId, settings)` (`lib/api/resume.ts`) after `TEMPLATE_SETTINGS_SAVE_DEBOUNCE_MS` = 700 ms, only while `loadingState === 'loaded'` so a slow GET cannot pin this resume to the previous one's template |
| Last-used default | `lib/utils/template-settings-storage.ts` — `readTemplateSettings` / `writeTemplateSettings` over `resume_builder_settings`, merged onto `DEFAULT_TEMPLATE_SETTINGS` with an unknown template id dropped and a payload lacking `settingsVersion: 2` upgraded from the old 1-5 spacing levels (+2 per spacing axis) |
| Viewer | `app/(default)/resumes/[id]/page.tsx` prefers `data.template_settings`, falls back to the stored last-used ones, renders `TexPdfPreview` or `<Resume settings={…}>` from them and passes them to `downloadResumePdf` |
| Inheritance | A tailored resume is created with its parent's `template_settings` |

### StatusCache Context

- Initial fetch on app start
- 30-min auto-refresh
- Optimistic counter updates

## Delete Flow

1. Click Delete → Confirmation dialog
2. API: `DELETE /resumes/{id}`
3. Clear localStorage if master
4. Success dialog → Redirect to dashboard

## Section Management

Sections are data, so the builder edits a list rather than a fixed set of
panels. Each row gets the same controls (see
[custom-sections.md](../features/custom-sections.md)):

| Action  | Result                                                                  |
| ------- | ----------------------------------------------------------------------- |
| Rename  | Pencil icon — edits `section.heading` (free text)                       |
| Reorder | Up/down arrows or drag — moves the item within `doc.sections`            |
| Column  | Toggle — flips `section.column` between `main` and `side`                |
| Hide    | Eye icon — `section.visible = false`; still editable, absent from the PDF |
| Delete  | Trash icon — removes the section (confirmation dialog)                  |
| Add     | "Add Section" — asks for a heading and a `SectionKind`, nothing else    |

## Registry-Driven Component Flow

Neither the editor nor the renderer enumerates resume sections. Both look up a
component by `section.kind`:

```
ResumeDocument
├── header ──────────────────────────────► PersonalInfoForm  /  template <header>
└── sections[] (list order = display order)
     ├── builder:  resume-form.tsx  → SECTION_KIND_FORMS[section.kind]
     │                                (components/builder/forms/index.ts)
     └── preview:  resume-{template} → visibleSections(doc)
                                     → SectionBlock
                                     → SECTION_KIND_RENDERERS[section.kind]
                                       (components/resume/section-kinds/index.ts)
```

Consequences worth remembering:

- A section with a key no component has heard of still renders and still edits.
- Two-column templates partition on `section.column`; single-column ones ignore it.
- Headings come from `sectionHeading(section, t)`, which translates a heading
  only while it still equals its `headingI18nKey`'s English default — a user
  heading is never passed to `t()`.
- `SectionHeader` owns rename/reorder/column/visibility/delete for every
  section uniformly.

## Diff surfaces

`components/diff/` is the one diff UI: `DiffView` (stats bar, unified/split
toggle, one collapsible group per section), `DiffRows` (a flat row list that
collapses unchanged runs of three or more rows behind an expander),
`DiffRowLine`, `DiffSectionGroup`, `DiffStatsBar` and `paths.ts`.

| Surface | Component | Rows come from |
| ------- | --------- | -------------- |
| Tailor preview modal | `components/tailor/diff-preview-modal.tsx` → `DiffView` | `ImproveResumeData.diff` |
| Regenerate preview | `components/builder/regenerate-diff-preview.tsx` → `DiffRows` | `RegeneratedItem.rows` |
| Compare page | `app/(default)/compare/page.tsx` → `DiffView` | `POST /diff` |

Nothing here computes a diff. Every row is server-computed, and section groups
are seeded from the response — sections are user-named, so no part of this can
key off a fixed list of section keys.

Passing `onAcceptedPathsChange` to `DiffView` turns it into a partial-accept
picker: each selectable row (a content leaf, per `paths.ts`) gets a checkbox,
and the tailor modal sends the selection as `accepted_paths` on confirm —
`null` when everything is still ticked, so the ordinary accept-the-tailoring
flow is one click. See
[document-diff.md](../features/document-diff.md#the-three-surfaces).

## API Client

```typescript
import { fetchResume, updateResume } from '@/lib/api/resume';
import type { ResumeDocument } from '@/lib/types/document';

const response = await fetchResume(resumeId);
if (response.processed_resume) {
  const doc: ResumeDocument = response.processed_resume;
  await updateResume(resumeId, { ...doc, sections: nextSections });
}
```

`PATCH` takes the **whole** document; the backend forbids unknown fields, so
round-trip what you were given instead of constructing a partial payload.

## Async ownership and acknowledged saves

`use-operation-owner.ts` invalidates late enrichment/regeneration results after reset, a resume change, or unmount. Generation, apply, and refresh are separate stages. Once regeneration or enrichment apply is acknowledged, a failed viewer refresh shows a saved-but-refresh-failed notice; Retry refresh fetches the saved resume without applying the changes again. Closing that notice or changing the viewer identity invalidates the pending refresh without undoing the durable save. Enrichment previews retain failed-item identities alongside successful enhancements, including after an apply failure and retry.

The tailor page records a confirmed server response before navigation and optimistic counters. Retrying navigation reuses that acknowledgement. Confirmation failure retries the same stored job and preview; the Generate action intentionally uploads a new job before making a new preview. Closing/rejecting the preview or leaving the route prevents late results from updating the current UI.

See the [reliability map](reliability-map.md) for file ownership, deterministic checks and the actual browser script. The browser fixture covers Next navigation and per-tab draft separation with synthetic API responses; backend transaction tests cover persistence separately.
