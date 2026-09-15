# Resume Template Settings

> **Template types and extensive formatting controls.**

## Render Targets

The templates and controls documented here belong to the **Chromium HTML** PDF
target (`GET /api/v1/resumes/{id}/pdf`). A second, independent target renders
the same document as real LaTeX (`tex-classic`, `tex-compact`) and compiles it
with a TeX engine — different templates, no CSS, its own small settings
surface: [latex-export.md](latex-export.md).

Both targets are chosen in the **same** picker (the template grid in
`components/builder/formatting-controls.tsx`; the LaTeX tab no longer owns a
template choice, it only offers to switch when an HTML template is selected).
`TEMPLATE_OPTIONS` (`lib/types/template-settings.ts`) lists nine templates —
the seven HTML ones below plus **LaTeX Classic** (`tex-classic`) and **LaTeX
Compact** (`tex-compact`) — and every row declares its
`target: 'html' | 'tex'`. `isTexTemplate()` reads that registry and is the only
predicate call sites use; nothing tests the id prefix. Selecting a LaTeX
template switches both the preview and the header's Download PDF to
`GET /api/v1/resumes/{id}/tex/pdf` (`compileTexPdf`): `getResumePdfUrl` throws
for a tex template, and the Chromium route answers **400** with a detail naming
`/tex/pdf` for any template outside the backend's `HTML_TEMPLATES`. The two
LaTeX options render disabled when `getTexCapabilities()` reports no engine.

> The HTML template id `latex` below is **not** the LaTeX export. It is a
> web layout styled to resemble LaTeX output, rendered by Chromium — which is
> why the UI labels it **Academic Serif**; only the stored id is still
> `latex`.

## Template Types

| Template | Description |
|----------|-------------|
| `swiss-single` | Traditional single-column layout with maximum content density |
| `swiss-two-column` | 65%/35% split with experience in main column, skills in sidebar |
| `modern` | Single-column with colorful accent headers and customizable theme colors |
| `modern-two-column` | Two-column layout combining modern accents with space-efficient design |
| `latex` (shown as **Academic Serif**) | Classic serif single-column with Title-Case ruled headers and company-first entries (LaTeX-*looking* HTML — unrelated to the [LaTeX export](latex-export.md)). Single-typeface — driven by the Header Font control |
| `clean` | Minimal sans single-column with large understated gray UPPERCASE headers and single-line entries. Single-typeface — driven by the Body Font control |
| `vivid` | Colorful two-column (Awesome-CV lineage): two-tone accent name, monospace contact with circular icons, accent small-caps headers, accent arrow bullets. Supports the Accent Color control |

## Formatting Controls

| Control | Range | Default | Effect |
|---------|-------|---------|--------|
| Margins | 5-25mm | 8mm | Page margins |
| Section Spacing | 1-5 | 3 | Gap between major sections |
| Item Spacing | 1-5 | 2 | Gap between items within sections |
| Line Height | 1-5 | 3 | Text line height |
| Base Font Size | 1-5 | 3 | Overall text scale (11-16px) |
| Header Scale | 1-5 | 3 | Name/section header size multiplier |
| Header Font | serif/sans-serif/mono | serif | Font family for headers |
| Body Font | serif/sans-serif/mono | sans-serif | Font family for body text |
| Compact Mode | boolean | false | Apply 0.6x spacing multiplier (spacing only; margins unchanged) |
| Contact Icons | boolean | false | Show icons next to contact info |
| Accent Color | blue/green/orange/red | blue | Accent color for color templates (modern, modern-two-column, vivid) |

Every control above except **Page Size** is CSS-driven, so it applies to the
HTML target only. With a LaTeX template selected, `FormattingControls` disables
margins, spacing, font sizes, header/body font, compact mode, contact icons and
accent colour and shows `builder.formatting.texNotice` under the template grid.
Page size stays live: the `/tex*` routes take `pageSize=A4|LETTER` and both
`.tex.j2` preambles select `a4paper`/`letterpaper` from it.

## Key Files

| File | Purpose |
|------|---------|
| `apps/frontend/lib/types/document.ts` | The resume document contract (`Section`, `SectionKind`, `Entry`, `Bullet`) every template consumes |
| `apps/frontend/components/resume/template-props.ts` | `ResumeTemplateProps` — the identical props every template takes |
| `apps/frontend/components/resume/section-kinds/` | `SECTION_KIND_RENDERERS` + `SectionBlock`: one renderer per `SectionKind` |
| `apps/frontend/lib/utils/section-helpers.ts` | `visibleSections`, `sectionHeading` |
| `apps/frontend/lib/types/template-settings.ts` | Type definitions, defaults, CSS variable mapping |
| `apps/frontend/components/resume/styles/_tokens.css` | Global design tokens (colors) |
| `apps/frontend/components/resume/styles/_base.module.css` | Shared typography and layout styles |
| `apps/frontend/components/builder/formatting-controls.tsx` | UI controls for template settings |
| `apps/frontend/components/resume/resume-single-column.tsx` | `swiss-single` |
| `apps/frontend/components/resume/resume-two-column.tsx` | `swiss-two-column` |
| `apps/frontend/components/resume/resume-modern.tsx` | `modern` |
| `apps/frontend/components/resume/resume-modern-two-column.tsx` | `modern-two-column` |
| `apps/frontend/components/resume/resume-latex.tsx` | `latex` |
| `apps/frontend/components/resume/resume-clean.tsx` | `clean` |
| `apps/frontend/components/resume/resume-vivid.tsx` | `vivid` |
| `apps/backend/app/routers/resumes.py` | PDF generation endpoint with accentColor support |

## CSS Variables

Templates use CSS custom properties for styling:

- `--section-gap`, `--item-gap`, `--line-height` - Spacing
- `--font-size-base`, `--header-scale`, `--section-header-scale` - Typography
- `--header-font` - Header font family
- `--body-font` - Body text font family
- `--margin-top/bottom/left/right` - Page margins
- `--accent-primary`, `--accent-light` - Accent colors for Modern templates

> **Note**: Templates should use the styles exported from `apps/frontend/components/resume/styles/_base.module.css` (e.g., `baseStyles['resume-section']`, `baseStyles['resume-item-subtitle']`) to ensure all spacing and typography respond to template settings.

### Typography Classes

The base stylesheet includes specialized classes for improved subtitle visibility:

| Class | Font Size | Weight | Usage |
|-------|-----------|--------|-------|
| `resume-item-subtitle` | 0.95× base | 600 | Company names, education degrees, project roles |
| `resume-item-subtitle-sm` | 0.88× base | 600 | Same fields in compact two-column layouts |

These classes provide **better visibility** than the generic `resume-meta` class (0.82× base, weight 400), making subtitles 13-16% larger and semi-bold.

Formatting controls include an "Effective Output" summary that reflects compact-mode adjustments for spacing/line-height.

---

## What a Template Consumes

Every template takes the same props (`components/resume/template-props.ts`):
a `ResumeDocument`, plus `showContactIcons` and a `fallbackName` for an empty
`header.name`. Template settings arrive as CSS variables, not props.

A template owns typography and layout only. It never enumerates sections:

- **Order** is `doc.sections` order — templates map `visibleSections(doc)`.
- **Heading** is `section.heading`, rendered verbatim by `SectionBlock` (the
  caller has already resolved any `headingI18nKey` through `sectionHeading`).
- **Shape** is `section.kind`, dispatched through `SECTION_KIND_RENDERERS`.
- **Column** is `section.column`: a two-column template partitions on
  `section.column === 'side'`, so any section can live in either column. A
  single-column template ignores the field.

So a section whose key no component has ever heard of renders in all seven HTML
templates with no code change (and in both LaTeX templates, which dispatch on
`section.kind` from the shared `_document.tex.j2` body). See
[adding-resume-templates.md](adding-resume-templates.md).

---

## Bullet Styles (`Bullet.style`)

Each bullet row under an entry renders **with** a bullet marker or as a
**plain** paragraph — used for sub-headings or continuation lines inside an
entry.

### Shape

The style is a property of the bullet, not of a parallel array:

```jsonc
{
  "bullets": [
    { "text": "Led the platform migration", "style": "plain" },
    { "text": "Rebuilt the ingest tier", "style": "bullet" }
  ]
}
```

`style` is `"bullet"` (default) or `"plain"`. Because it travels with its own
text, filtering, reordering, appending or deleting rows cannot desync a marker
onto its neighbour — there is no alignment invariant to maintain and nothing to
enforce in the editor, the client normalizer, the server schema or the prompts.

`style` is in the AI's blocked-field list, so a tailoring change can rewrite a
bullet's `text` but never restyle it. `apply_diffs` appends new bullets as
`{"text": …, "style": "bullet"}`. `refiner._restore_bullet_styles` restores
styles after keyword injection — the last writer on the improve path — matching
the defence-in-depth pattern used for dates, skills and the header.

### Rendering

All seven HTML templates render bullets through the single `entries` renderer,
`apps/frontend/components/resume/section-kinds/entries-section.tsx`, which omits
the marker span (and its indent) when the style is `"plain"`. The marker is
`aria-hidden="true"`. The JD-match preview
(`apps/frontend/components/builder/highlighted-resume-view.tsx`) reads the same
`bullet.style` and applies the same rule, so the builder cannot contradict the
PDF.

The LaTeX target follows the same rule from the other side:
`apps/backend/app/latex/templates/_document.tex.j2` emits `\item[]` for a
`"plain"` bullet and `\item` otherwise, so both render targets agree.

Coverage: `apps/frontend/tests/section-registry.test.tsx` runs every template
over one document and asserts per-kind content, the plain/bullet marker rule and
hidden-section exclusion; `apps/frontend/tests/template-registration.test.ts`
pins the template registry (all nine ids, unique, each with a `target`, and
exactly the two `tex-` ids routed to the LaTeX target, plus the font presets).
