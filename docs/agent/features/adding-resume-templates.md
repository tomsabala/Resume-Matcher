# Adding Resume Templates

> Guide for adding a new resume template layout.

A template is **presentation only**: typography, spacing and column geometry.
It does not know what sections a resume has. Section content is rendered by the
kind registry in
[`components/resume/section-kinds/`](../../../apps/frontend/components/resume/section-kinds/),
which every template shares.

Two different jobs are easy to confuse:

| Job | How often | What you touch |
|---|---|---|
| **Add a template** — a new look | common | one new `resume-*.tsx`, its CSS module, the registries below |
| **Add a section kind** — a new *content shape* | rare | `SectionKind` in the contract, one renderer, one builder form |

Adding a *section* to a resume is neither: sections are user data
(see [custom-sections.md](custom-sections.md)).

---

## Adding a Template

### 1. Create the component

`apps/frontend/components/resume/resume-{name}.tsx`. Every template takes the
same props from `./template-props`:

```tsx
import React from 'react';
import { visibleSections } from '@/lib/utils/section-helpers';
import type { ResumeTemplateProps } from './template-props';
import { ContactValue } from './contact';
import { SectionBlock } from './section-kinds/section-block';
import baseStyles from './styles/_base.module.css';
import styles from './styles/my-template.module.css';

export const ResumeMyTemplate: React.FC<ResumeTemplateProps> = ({
  doc,
  showContactIcons = false,
  fallbackName,
}) => {
  const { header } = doc;

  return (
    <>
      <header className={baseStyles['resume-header']}>
        {(header.name || fallbackName) && (
          <h1 className={baseStyles['resume-name']}>{header.name || fallbackName}</h1>
        )}
        {header.headline && <h2 className={baseStyles['resume-title']}>{header.headline}</h2>}
        {header.contacts.map((contact) => (
          <ContactValue key={contact.id} contact={contact} showIcon={showContactIcons} />
        ))}
      </header>

      {visibleSections(doc).map((section) => (
        <SectionBlock
          key={section.id}
          section={section}
          headingClassName={styles.sectionTitle}
        />
      ))}
    </>
  );
};
```

That is the whole contract:

- **`doc.header`** is rendered by the template itself — it is not a section.
- **`visibleSections(doc)`** gives the visible sections in document order.
  Nothing is sorted, filtered by name, or enumerated.
- **`SectionBlock`** renders the heading (using your `headingClassName`) and
  dispatches the body through `SECTION_KIND_RENDERERS[section.kind]`. It renders
  nothing for a section with no content.

Headings arrive already localized: the caller maps sections through
`sectionHeading` before rendering, so a template renders `section.heading`
verbatim and never calls `t()`.

### 2. Two-column layouts partition on `section.column`

```tsx
const sections = visibleSections(doc);
const mainSections = sections.filter((section) => section.column !== 'side');
const sideSections = sections.filter((section) => section.column === 'side');
```

Placement is the user's data, not a hardcoded list of which sections may appear
in a sidebar. A single-column template simply ignores `column`.

### 3. Register it

| Where | What to add |
|---|---|
| `components/resume/index.ts` | `export { ResumeMyTemplate } from './resume-my-template';` |
| `lib/types/template-settings.ts` → `TemplateType` | the new id (`'my-template'`) |
| `lib/types/template-settings.ts` → `TEMPLATE_OPTIONS` | `{ id, name, description }` for the selector UI |
| `lib/types/template-settings.ts` → `TEMPLATE_FONT_PRESETS` | only if the template is single-typeface and needs signature fonts |
| `components/dashboard/resume-component.tsx` → `TEMPLATE_COMPONENTS` | id → component (this `Record<TemplateType, …>` is exhaustive, so `tsc` fails until you add it) |
| `app/print/resumes/[id]/page.tsx` → `parseTemplate` allow-list | the new id, so the PDF route accepts it |

`TEMPLATE_OPTIONS` drives the selector; there is no second literal list of
template names to update.

### 4. CSS

Add `components/resume/styles/my-template.module.css` and use the shared
`_base.module.css` classes so the formatting controls keep working.

A template returns the header plus its section blocks — it does **not** own the
root element. The `.resume-print` wrapper that Playwright waits for belongs to
the page (`app/print/resumes/[id]/page.tsx` and the viewer), so do not add it.
`SectionBlock` and the kind renderers already emit the structural classes:

```css
.resume-section        /* Section wrapper */
.resume-items          /* Items container */
.resume-item           /* Individual entry (must not page-break) */
```

Spacing and typography must read the CSS variables produced by
`settingsToCssVars` (`--section-gap`, `--item-gap`, `--line-height`,
`--font-size-base`, `--header-scale`, `--header-font`, `--body-font`,
`--resume-accent-primary`), otherwise the formatting controls silently do
nothing for your template.

### 5. Verify

1. Open `/builder`, select the template, confirm the header and **every** kind
   renders: a `text` section, an `entries` section with a `summary` and both
   bullet styles, a `tags` section and a `groups` section.
2. Add a brand-new section from **Add Section** and confirm it renders with no
   code change.
3. For a two-column template, flip a section to the sidebar and back.
4. Download the PDF (needs the backend + `playwright install chromium`).
5. Test with 2+ pages of content and confirm entries do not split.

Two specs need the new id too: add the component to the `TEMPLATES` list in
`apps/frontend/tests/section-registry.test.tsx` (it then renders your template
over the shared document and asserts every kind, both bullet styles and
hidden-section exclusion), and update the id list/count in
`tests/template-registration.test.ts`.

---

## Adding a Section Kind

Rare — only when a genuinely new *content shape* is needed (the existing four
are `text`, `entries`, `tags`, `groups`).

1. Add the value to `SectionKind` in **both**
   `apps/backend/app/schemas/document.py` and
   `apps/frontend/lib/types/document.ts`, plus the field that holds its content
   on `Section`.
2. Add a renderer in `components/resume/section-kinds/` and register it in
   `SECTION_KIND_RENDERERS`; teach `sectionHasContent` (in
   `section-kinds/content.ts`) what "empty" means for it.
3. Add an editor in `components/builder/forms/` and register it in
   `SECTION_KIND_FORMS`; add an icon to `KIND_ICONS`/`KIND_ORDER` in
   `add-section-dialog.tsx` and a
   `builder.sectionForms.kinds.<kind>.{label,description}` entry to every
   locale file.
4. Extend `improver.build_allowed_paths` with the change path(s) the new kind
   exposes, and `document_walk` if the new content is prose or short values the
   traversal helpers should see.

Both registries are typed `Record<SectionKind, …>`, so steps 2 and 3 are
enforced by the compiler: the build stays red until the new kind has a renderer
and a form. Every template then supports it with no template changes at all.
