# Resume Sections

> **Every section of a resume is the same kind of object. There is no built-in set and no "custom" set.**

A resume document is `{ schemaVersion: 2, header, sections: Section[] }`. The
header is not a section — every template renders it outside the section loop.
Everything below the header is a `Section`, whether it arrived from the resume
parser, from the wizard, or from the user clicking **Add Section**.

Because sections are data, adding one to a resume never requires code. The word
"custom" has no meaning here: a section the user typed and a section named
"Experience" are indistinguishable to every renderer, editor, AI allowlist and
diff rule.

## Section Kinds

`Section.kind` is the only thing that decides how a section behaves. Four kinds
exist; the contract is
[`apps/backend/app/schemas/document.py`](../../../apps/backend/app/schemas/document.py)
and its mirror
[`apps/frontend/lib/types/document.ts`](../../../apps/frontend/lib/types/document.ts).

| Kind | Content field | Shape | Typical use |
|---|---|---|---|
| `text` | `section.text` | One prose block | Summary, objective, personal statement |
| `entries` | `section.entries` | `Entry[]` | Experience, education, projects, publications, military service |
| `tags` | `section.tags` | `string[]` | Spoken languages, hobbies, interests |
| `groups` | `section.groups` | `TagGroup[]` (`{ label, values }`) | Skills grouped by category, certifications, awards |

An `Entry` is deliberately generic — `title`/`subtitle` are job title/company
for one section, institution/degree for another, project name/role for a third:

```ts
interface Entry {
  id: string;        // stable for the entry's life; used in enrichment item ids
  title: string;
  subtitle: string;
  meta: string;      // location or other free metadata
  period: string;    // "2023 -- May 2026"; stored verbatim, never parsed
  links: EntryLink[];
  summary: string;   // the paragraph above the bullets
  bullets: Bullet[]; // each bullet carries its own `style: 'bullet' | 'plain'`
}
```

`summary` and `bullets` coexist, so an entry can have a paragraph *and* bullets.

## Section Fields

| Field | Meaning |
|---|---|
| `id` | Opaque identity for React keys and drag-and-drop |
| `key` | Slug, unique per document. Used in AI change paths, diff paths and enrichment item ids — **not** display text |
| `heading` | The user's own headline, free text |
| `headingI18nKey` | Set only on sections projected from a v1 built-in; see [Headings and i18n](#headings-and-i18n) |
| `kind` | One of the four kinds above |
| `visible` | `false` hides the section from the preview and PDF; it stays editable |
| `column` | `'main'` or `'side'` — how two-column templates partition |

**Order is list order.** `doc.sections` is the display order; reordering is an
array move, with no separate order field to keep in step.

### Keys

`createSection` (frontend) and `slugify_key` (backend) slugify the heading and
append `_2`, `_3`… on collision. A key is stable once created: renaming a
section's heading does not change its key, so AI change paths and in-flight
enrichment items keep resolving.

## Headings and i18n

Sections projected from the v1 built-ins carry a `headingI18nKey` such as
`resume.sections.experience`. The rule, implemented once in
`sectionHeading()` ([`apps/frontend/lib/utils/section-helpers.ts`](../../../apps/frontend/lib/utils/section-helpers.ts)):

> Render `t(section.headingI18nKey)` **only while `section.heading` still equals
> that key's English default.** The moment the user edits the heading, the
> literal text wins.

A user-authored heading must never be passed to `t()`. `Messages = typeof en`
makes an unknown key a build failure, and the lookup would echo the path back to
the user as their section title. Sections created by the user have
`headingI18nKey === null` and are always rendered verbatim.

Templates themselves receive already-resolved headings: callers map sections
through `sectionHeading` before handing the document to a template, and
`SectionBlock` renders `section.heading` as-is.

## Section Controls (UI)

The builder's form list renders one `SectionHeader` per section
([`apps/frontend/components/builder/section-header.tsx`](../../../apps/frontend/components/builder/section-header.tsx)).
Every section gets the same controls — the header (name, headline, contacts) is
edited by its own form and has none of them.

| Control | Icon | Function |
|---|---|---|
| Rename | Pencil | Edit `heading` (inline input; Enter saves, Escape cancels) |
| Column | Columns2 | Flip `column` between `main` and `side`; a `side` section shows a "sidebar" tag (single-column templates ignore the field) |
| Visibility | Eye / EyeOff | Toggle `visible`; a hidden section shows a "hidden from PDF" tag |
| Move up / down | ChevronUp / ChevronDown | Move the section within `doc.sections` |
| Delete | Trash2 | Remove the section from `doc.sections` (confirmation dialog) |

Sections can also be dragged (`DraggableSectionWrapper`).

**Add Section** (`add-section-dialog.tsx`) asks for exactly two things: a
heading and a kind. That is the whole creation contract.

### Hidden sections

A hidden section renders with a dashed border, reduced opacity and a
"hidden from PDF" badge, and stays fully editable. Only the render path filters
it: templates, the preview and the JD-match view map `visibleSections(doc)`,
while the builder form iterates the whole `doc.sections` list (`allSections` is
the named helper for that).

## Rendering and Editing

Both sides are registry lookups keyed by `kind`, not conditionals over section
names:

| Concern | Registry | File |
|---|---|---|
| Render | `SECTION_KIND_RENDERERS` | [`components/resume/section-kinds/index.ts`](../../../apps/frontend/components/resume/section-kinds/index.ts) |
| Edit | `SECTION_KIND_FORMS` | [`components/builder/forms/index.ts`](../../../apps/frontend/components/builder/forms/index.ts) |

Both are typed `Record<SectionKind, …>`, so adding a kind to the contract fails
the build until a renderer and a form exist for it. See
[adding-resume-templates.md](adding-resume-templates.md) for how a template
consumes them.

## AI Editability

User-created sections are AI-editable. The allowlist is generated per document
by `improver.build_allowed_paths`, from the document's own sections and their
kinds — there is no fixed list of section names to be absent from.

Editable (content):

```
sections.<key>.text
sections.<key>.entries[i].summary
sections.<key>.entries[i].bullets
sections.<key>.entries[i].bullets[j].text
sections.<key>.tags
sections.<key>.groups[i].values
```

Never editable (identity and structure): `header.*`, `schemaVersion`, and the
fields `id`, `key`, `kind`, `heading`, `headingI18nKey`, `visible`, `column`,
`title`, `subtitle`, `meta`, `period`, `links`, `label`, `style`. The wire-level
contract for a change is in
[front-end-apis.md](../apis/front-end-apis.md#ai-change-paths).

Note that `sections.<key>` resolves a section **by key**, not by position: the
path segment matches the list item whose `key` field equals the segment, so a
user reorder between generation and apply cannot retarget a different section.

## Key Files

| File | Purpose |
|---|---|
| `apps/backend/app/schemas/document.py` | The contract: `Section`, `SectionKind`, `Entry`, `Bullet`, `TagGroup`, `Header`, `migrate_document` |
| `apps/backend/app/services/document_walk.py` | Section-agnostic traversal (`iter_sections`, `iter_entries`, `skill_values`, `document_text_fragments`) |
| `apps/frontend/lib/types/document.ts` | Frontend mirror of the contract |
| `apps/frontend/lib/utils/section-helpers.ts` | `visibleSections`, `allSections`, `createSection`, `sectionHeading` |
| `apps/frontend/components/resume/section-kinds/` | One renderer per kind + `SectionBlock` + `SECTION_KIND_RENDERERS` |
| `apps/frontend/components/builder/forms/` | One editor per kind + `SECTION_KIND_FORMS` (plus `personal-info-form.tsx` for the header) |
| `apps/frontend/components/builder/section-header.tsx` | Per-section controls |
| `apps/frontend/components/builder/add-section-dialog.tsx` | Heading + kind, nothing else |

## Reading Older Resumes

Resumes stored under schema version 1 had a fixed six-section shape
(`personalInfo`, `summary`, `workExperience`, `education`, `personalProjects`,
`additional`) plus `sectionMeta` for order/visibility and a `customSections` map
for anything else. `migrate_document(raw)` in
`apps/backend/app/schemas/document.py` projects such a row onto the v2 document
on read, and is the only place those names still appear:

| v1 | v2 |
|---|---|
| `personalInfo` | `header` (name, headline, contacts) |
| `summary` | section `summary`, kind `text` |
| `workExperience` | section `experience`, kind `entries` |
| `education` | section `education`, kind `entries` |
| `personalProjects` | section `projects`, kind `entries` |
| `additional.*` buckets | section `skills`, kind `groups` |
| `customSections.<name>` | a section whose `kind` comes from the old `sectionType` (`text`/`itemList`/`stringList`) |
| `sectionMeta[].displayName` / `.visible` / `.order` | `heading` / `visible` / position in `sections` |
| `description` + `descriptionStyles` | `bullets: Bullet[]`, zipped by index once, at migration time |

The projection runs on read only; nothing writes v1 shapes. `ResumeDocument`
sets `extra="forbid"`, so an unrecognized field is a validation error rather
than — as in v1 — silently dropped content.
