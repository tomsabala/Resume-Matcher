# PDF Template Guide

> PDF rendering and template editing for resumes and cover letters.

> **Scope.** This document covers the **Chromium HTML** PDF target. There is a
> second, independent target that renders the same resume document as real
> LaTeX and compiles it with a TeX engine (`GET /resumes/{id}/tex/pdf`,
> templates `tex-classic`/`tex-compact`) — see
> [latex-export.md](../features/latex-export.md). Both targets are chosen in
> the **same** picker: each `TEMPLATE_OPTIONS` row declares its
> `target: 'html' | 'tex'` and `isTexTemplate()` is the predicate that routes
> the export, so this route is never *meant* to see a LaTeX template — and no
> longer silently renders one as `swiss-single`. `GET /resumes/{id}/pdf`
> answers **400** with a detail naming `/tex/pdf` for any template outside
> `HTML_TEMPLATES` (`app/routers/resumes.py`). The `latex` template id below
> belongs to *this* Chromium path: it is an HTML layout that resembles LaTeX
> output (labelled **Academic Serif** in the UI), not the LaTeX export.

## Rendering Flow

```
Backend: GET /resumes/{id}/pdf
├── Build URL: {frontend}/print/resumes/{id}?params
├── Playwright opens headless Chrome
├── Waits for .resume-print selector
├── Waits for document.fonts.ready
├── Generates PDF (zero margins, print_background=true)
└── Returns PDF bytes
```

## Print Routes

| Route | Selector | Output |
|-------|----------|--------|
| `/print/resumes/[id]` | `.resume-print` | Resume PDF |
| `/print/cover-letter/[id]` | `.cover-letter-print` | Cover letter PDF |

## Renderer Limits

| Environment variable | Default | Supported range | Purpose |
|----------------------|---------|-----------------|---------|
| `PDF_MAX_CONCURRENCY` | 4 | 1-16 | Maximum active exports; excess requests fail immediately instead of queueing |
| `PDF_RENDER_TIMEOUT_SECONDS` | 75 | 1-600 | Total export lifetime, including browser/page creation and cleanup |
| `PDF_CLEANUP_RESERVE_SECONDS` | 5 | 0.1-30 | Portion of the total lifetime reserved for resource cleanup |

The renderer replaces a disconnected cached browser automatically. On Windows
event loops that require the thread fallback, a cancelled or timed-out request
continues to occupy its concurrency slot until its bounded worker exits.
If page cleanup exceeds its reserve, the shared browser is retired and its
teardown retains a slot; saturated follow-up requests receive the same immediate
busy outcome until cleanup finishes, after which a healthy browser is created.
Cancellation during page cleanup also retires the browser and propagates the
cancellation; capacity remains owned until browser and Playwright teardown finish.
An ordinary Playwright error while closing the page is logged and retires the
browser, but does not discard an already-generated PDF or replace an earlier
render failure. Exceeding the cleanup deadline still makes an otherwise successful
export time out.

Retirement immediately removes that browser from the cache, so new exports cannot
join it. Existing exports keep using their own pages until their render and page
cleanup scopes finish; only then does the retirement owner close the shared
browser. Concurrent cleanup failures therefore retire that generation only once
without aborting or replaying healthy exports. The retirement reservation owns
unclosed resources independently of the existing exports' request slots; it is
kept while those exports use their existing deadlines to finish.

A successful stop of the owned Playwright driver is a teardown acknowledgement,
even if its Browser object retains a stale `is_connected()` flag. If driver
shutdown fails, cleanup quarantines its browser/driver objects and admission slot
until application restart. Playwright's stop method is one-shot, so retrying a
failed stop can return without doing any cleanup; such a return is not accepted
as proof of teardown. Quarantine logs the failure and completes the cleanup task
instead of leaving an unsignalled waiter. Application shutdown reports any
quarantined generations and waits for still-active cleanup owners within the
cleanup reserve; it does not cancel them or release their capacity prematurely.
If an external shutdown cancels retirement before teardown is acknowledged,
including before the cleanup task first runs, its browser/driver and reservation
move into the same terminal quarantine. Cancellation still propagates. This
retains explicit ownership; it does not claim the browser was physically stopped.

## Query Parameters

| Param | Default | Range |
|-------|---------|-------|
| template | swiss-single | swiss-single, swiss-two-column, modern, modern-two-column, latex, clean, vivid (HTML only — a `tex-*` id is a 400) |
| pageSize | A4 | A4, LETTER |
| marginTop/Bottom/Left/Right | 10 | 5-25mm |
| sectionSpacing | 3 | 1-5 |
| itemSpacing | 2 | 1-5 |
| lineHeight | 3 | 1-5 |
| fontSize | 3 | 1-5 |
| headerScale | 3 | 1-5 |

## Critical CSS Rule

In `globals.css`, whitelist print classes or PDFs will be blank:

```css
@media print {
  body * { visibility: hidden !important; }
  
  .resume-print,
  .resume-print * { visibility: visible !important; }
  
  .cover-letter-print,
  .cover-letter-print * { visibility: visible !important; }
}
```

## Template Structure

```
components/resume/
├── index.ts                    # Template exports
├── template-props.ts           # ResumeTemplateProps
├── resume-single-column.tsx    # swiss-single — full-width vertical
├── resume-two-column.tsx       # swiss-two-column — 65% main + 35% sidebar
├── resume-modern.tsx           # modern
├── resume-modern-two-column.tsx
├── resume-latex.tsx            # latex — LaTeX-looking HTML, not the LaTeX export
├── resume-clean.tsx            # clean
├── resume-vivid.tsx            # vivid
└── section-kinds/              # shared per-kind renderers + SectionBlock
```

## Adding New Templates

See [adding-resume-templates.md](../features/adding-resume-templates.md). Two
registries fail quietly: add the id to `parseTemplate` in
`app/print/resumes/[id]/page.tsx` (an HTML-only allow-list, by design) or the
PDF silently falls back to `swiss-single`, and to `TEMPLATE_COMPONENTS` in
`components/dashboard/resume-component.tsx` — now a
`Partial<Record<TemplateType, …>>`, so a missing entry compiles and falls back
to `ResumeSingleColumn` instead of rendering your template.

## Template Props

```typescript
interface ResumeTemplateProps {
  doc: ResumeDocument;
  showContactIcons?: boolean;
  fallbackName?: string; // placeholder for an empty header.name, already localized
}
```

Template settings reach the template as CSS variables on the wrapper
(`settingsToCssVars`), not as a prop. The template renders `doc.header` itself
and maps `visibleSections(doc)` through `SectionBlock`, which dispatches on
`section.kind` — it never enumerates sections.

## CSS Classes

```css
.resume-section        /* Section container */
.resume-section-title  /* Section heading */
.resume-items          /* Items container */
.resume-item           /* Individual entry (won't split across pages) */
```

## Error Handling

If Playwright can't connect to frontend, returns HTTP 503 with:
```
Cannot connect to frontend for PDF generation.
Please ensure: 1) Frontend is running
              2) FRONTEND_BASE_URL matches your frontend URL
```
