# Template System

> Resume template architecture and customization.

## Render Targets

The same `ResumeDocument` feeds two independent renderers:

| Target | Endpoint | How | Template ids |
| ------ | -------- | --- | ------------ |
| **Chromium HTML** | `GET /api/v1/resumes/{id}/pdf` | React templates in `components/resume/`, printed by headless Chromium via Playwright | `swiss-single`, `swiss-two-column`, `modern`, `modern-two-column`, `latex`, `clean`, `vivid` |
| **LaTeX** | `GET /api/v1/resumes/{id}/tex/pdf` | Jinja `.tex.j2` templates in `apps/backend/app/latex/templates/`, compiled by a TeX engine | `tex-classic`, `tex-compact` |

Both targets are chosen in **one** picker. `TEMPLATE_OPTIONS`
(`apps/frontend/lib/types/template-settings.ts`) has nine rows, and every row
carries `target: 'html' | 'tex'`. `isTexTemplate(template)` reads that registry
and is the single predicate every call site uses — nothing pattern-matches on an
id prefix. The selection therefore decides the export, so neither renderer can
silently produce a PDF for a template that belongs to the other:

- a `tex` selection previews and downloads through
  `GET /api/v1/resumes/{id}/tex/pdf` (`compileTexPdf` in `lib/api/tex.ts`), and
  `getResumePdfUrl` throws instead of emitting a Chromium URL for it;
- `GET /api/v1/resumes/{id}/pdf` answers **400** with a detail naming
  `/tex/pdf` for any template outside `HTML_TEMPLATES`
  (`apps/backend/app/routers/resumes.py`) — it used to accept any string and
  render `swiss-single`;
- the two `tex` options are offered **disabled** when `getTexCapabilities()`
  reports no engine, since they would 503 on every preview and download.

Everything below this section describes the **Chromium HTML** target: its
templates, its `TemplateSettings` and its CSS. The LaTeX target has its own
templates, its own (much smaller) settings surface and no CSS at all — see
[latex-export.md](../features/latex-export.md).

> **Do not confuse `latex` with the LaTeX export.** `latex` is an HTML
> template that *looks* like LaTeX output and is rendered by Chromium. The
> LaTeX export's ids are the `tex-` prefixed ones.

## Templates

| Template          | Layout                              | Best For                                 |
| ----------------- | ----------------------------------- | ---------------------------------------- |
| swiss-single      | Full-width vertical                 | 1-2 page resumes                         |
| swiss-two-column  | 65% main + 35% sidebar              | Dense content                            |
| modern            | Single column, accent headers       | Colorful single-column                   |
| modern-two-column | 65% main + 35% sidebar, accent      | Colorful dense content                   |
| latex             | Single column, serif, ruled headers | Classic/academic résumés (HTML, not the LaTeX export) |
| clean             | Single column, minimal sans         | Understated modern résumés               |
| vivid             | 63% main + 37% sidebar, accent      | Colorful Awesome-CV style (accent color) |

## File Structure

```
components/resume/
├── index.ts                      # Re-exports all templates
├── template-props.ts             # ResumeTemplateProps — identical for every template
├── resume-single-column.tsx      # swiss-single
├── resume-two-column.tsx         # swiss-two-column
├── resume-modern.tsx             # modern
├── resume-modern-two-column.tsx  # modern-two-column
├── resume-latex.tsx              # latex
├── resume-clean.tsx              # clean
├── resume-vivid.tsx              # vivid
├── section-kinds/                # SECTION_KIND_RENDERERS + SectionBlock:
│                                 #   one renderer per SectionKind, shared by all templates
├── contact.tsx                   # header contact / entry-link rendering
├── safe-html.tsx                 # sanitized rich-text renderer
└── styles/                       # *.module.css per template + _base/_tokens
```

## Template Settings

Authoritative definition: `apps/frontend/lib/types/template-settings.ts` (`TemplateSettings`,
`DEFAULT_TEMPLATE_SETTINGS`, and the CSS-variable maps). Current shape:

```typescript
interface TemplateSettings {
  settingsVersion: 2; // level-vocabulary marker; absent = v1, upgraded on read
  template:
    | "swiss-single"
    | "swiss-two-column"
    | "modern"
    | "modern-two-column"
    | "latex"
    | "clean"
    | "vivid"
    | "tex-classic" // LaTeX target
    | "tex-compact"; // LaTeX target
  pageSize: "A4" | "LETTER";
  margins: { top: number; bottom: number; left: number; right: number }; // 5-25mm each
  spacing: {
    // SpacingLevel = 1…9
    section: SpacingLevel; // neutral 5
    item: SpacingLevel; // neutral 4
    lineHeight: SpacingLevel; // neutral 5
    bulletLeadIn: SpacingLevel; // neutral 4 — LaTeX templates only
  };
  fontSize: {
    // FontLevel = 1…5 — `extarticle`/`extsizes` has 8/9/10/11/12pt and
    // nothing below 8pt, so these axes have no step to add downward
    base: FontLevel; // neutral 3
    headerScale: FontLevel; // neutral 3
    headerFont: "serif" | "sans-serif" | "mono";
    bodyFont: "serif" | "sans-serif" | "mono";
  };
  compactMode: boolean;
  showContactIcons: boolean;
  accentColor: "blue" | "green" | "orange" | "red"; // modern, modern-two-column, vivid
}
```

`settingsVersion: 2` is on every payload the frontend writes. A stored payload
without it is v1, whose spacing levels ran 1-5, and v1 and v2 level numbers
overlap — so the payload alone is ambiguous and the marker is what tells them
apart. `readTemplateSettings`
(`apps/frontend/lib/utils/template-settings-storage.ts`) and the backend's
`_parse_template_settings` (`apps/backend/app/routers/resumes.py`) upgrade such
a payload identically by adding 2 to each spacing level (so the old 1-5 land on
3-7, the same physical values as before, and nothing reflows); the font levels
and every other field are untouched. Per-level values for both renderers:
[latex-export.md](../features/latex-export.md#what-a-level-actually-means).

With a `tex` template selected, the engine reads `pageSize`, `margins`,
`spacing`, `fontSize.base`, `fontSize.headerScale` and `compactMode`: the
`/tex*` routes take them as query parameters and
`apps/backend/app/latex/layout.py` turns them into preamble values. The
font families, `showContactIcons` and `accentColor` are CSS-driven and
HTML-only, so `FormattingControls` disables exactly those for a `tex`
selection rather than letting them appear to work.

## Section Order and Placement

There is no fixed section order. `doc.sections` **is** the order, and the
header is rendered outside the section loop by each template. Two-column
templates partition on `section.column` (`'main'` | `'side'`); single-column
templates ignore it. A freshly parsed resume happens to arrive as summary →
experience → education → projects → skills, but that is data the user can
reorder, rename, hide or delete.

## The Resume Document

Authoritative definition: `apps/frontend/lib/types/document.ts`, mirroring
`apps/backend/app/schemas/document.py`.

```typescript
interface ResumeDocument {
  schemaVersion: 2;
  header: Header;      // name, headline, contacts — not a section
  sections: Section[]; // list order is display order
}

interface Section {
  id: string;
  key: string;                    // slug; used in AI change paths, never displayed
  heading: string;                // user-authored, free text
  headingI18nKey?: string | null; // only on sections projected from a v1 built-in
  kind: 'text' | 'entries' | 'tags' | 'groups';
  visible: boolean;
  column: 'main' | 'side';
  text: string;      // kind === 'text'
  entries: Entry[];  // kind === 'entries'
  tags: string[];    // kind === 'tags'
  groups: TagGroup[]; // kind === 'groups'
}
```

Full field-by-field description: [custom-sections.md](../features/custom-sections.md).

## Section Kinds

`Section.kind` is the only thing a template or editor dispatches on. Both
registries are `Record<SectionKind, …>`, so a new kind is a compile error until
it has a renderer and a form.

| Kind | Renderer (`components/resume/section-kinds/`) | Editor (`components/builder/forms/`) | Use case |
| ---- | --------------------------------------------- | ------------------------------------ | -------- |
| `text` | `TextSection` | `GenericTextForm` | Summary, objective, statement |
| `entries` | `EntriesSection` | `GenericItemForm` | Experience, education, projects, publications |
| `tags` | `TagsSection` | `GenericListForm` | Languages, hobbies, interests |
| `groups` | `GroupsSection` | `GroupsForm` | Skills/certifications grouped by label |

Users create sections through `AddSectionDialog`, which asks only for a heading
and a kind; the result is indistinguishable from any other section.

## CSS Classes

```css
.resume-section        /* Section wrapper */
.resume-section-title  /* Section heading (h3) */
.resume-items          /* Items container */
.resume-item           /* Single entry (won't page-break) */
```

## Spacing Variables

```css
--section-gap:   /* SECTION_SPACING_MAP[spacing.section]   — 2…40px  */
--item-gap:      /* ITEM_SPACING_MAP[spacing.item]         — 0…32px  */
--line-height:   /* LINE_HEIGHT_MAP[spacing.lineHeight]    — 1.05…1.85 */
```

A level is a table lookup, not a `calc()` on the level number: the three maps
live in `lib/types/template-settings.ts` and their steps are uneven on purpose
(tight at the bottom, generous at the top). `compactMode` multiplies the two
gaps by `COMPACT_MULTIPLIER` and the leading by
`COMPACT_LINE_HEIGHT_MULTIPLIER`. Full per-level table:
[latex-export.md](../features/latex-export.md#what-a-level-actually-means).

## Adding a Template

See [adding-resume-templates.md](../features/adding-resume-templates.md) for the
full walkthrough. In short: create `components/resume/resume-{name}.tsx`
implementing `ResumeTemplateProps`, render `doc.header` plus
`visibleSections(doc)` through `SectionBlock`, then register the id in
`index.ts`, `TemplateType`, `TEMPLATE_OPTIONS` (with `target: 'html'`),
`TEMPLATE_COMPONENTS` and the print route's `parseTemplate` allow-list.
`TEMPLATE_COMPONENTS` is a `Partial<Record<TemplateType, …>>` — the `tex-` ids
have no React component — so a missing HTML entry is **not** a compile error:
the lookup falls back to `ResumeSingleColumn` and your template never renders.

A **LaTeX** template is a different job: add a `.tex.j2` preamble beside
`apps/backend/app/latex/templates/_document.tex.j2`, include the shared body,
and register its id in `LATEX_TEMPLATES` (`app/latex/render.py`) plus
`TemplateType`/`TEMPLATE_OPTIONS` with `target: 'tex'` so the picker offers it.
It needs no React component, no CSS and no print-route entry, and it must stay
out of the backend's `HTML_TEMPLATES` so the Chromium route keeps rejecting it.
