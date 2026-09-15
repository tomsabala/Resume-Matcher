# Document diff

> **One engine compares two resume documents. Every diff the user ever sees is that engine's output rendered by one component.**

A diff is a *tree* diff, not a line diff: sections pair with sections, entries
pair inside their section, and only the leaves (a prose block, an entry's
summary, a bullet, a short value) are compared as text. That is what makes a
renamed heading read as a rename and a reordered entry read as a move, instead
of as a delete plus an add.

The engine is
[`apps/backend/app/services/document_diff.py`](../../../apps/backend/app/services/document_diff.py);
its wire shape is
[`apps/backend/app/schemas/diff.py`](../../../apps/backend/app/schemas/diff.py).

## Why one engine

Three features ask "what changed?" — tailoring, AI regeneration and version
history. All three are callers of the same engine, through three entry points:

| Function | Compares | Returns |
|---|---|---|
| `diff_documents(base, head, context=2)` | two whole `ResumeDocument`s | `DocumentDiff` |
| `diff_value_lists(base, head, path=…, kind=…)` | two lists of lines (an entry's bullets, a group's values) | `list[DiffRow]` |
| `merge_accepted(base, head, accepted_paths)` | — | `ResumeDocument` with only the named changes taken from `head` |

Every pairing rule and threshold is a module constant, deliberately not
configurable: a diff whose thresholds vary per deployment is a diff nobody can
reason about.

## Pairing rules

Pairing runs top-down. At each level the first rule that matches wins, and a
head item can only be claimed once.

| Level | Rules, in order | Threshold |
|---|---|---|
| Section | exact `section.id` → exact `section.heading` → closest `heading` by similarity → equal `section.key` | `0.80` on the heading |
| Entry | exact `entry.id` → exact `"{title} {subtitle}"` → closest `"{title} {subtitle}"` by similarity | `0.80` |
| Group (in a `groups` section) | exact `label` → closest `label` by similarity | `0.80` |
| Bullets, tags, group values, `.tex` lines | positional, via `SequenceMatcher` opcodes; inside a `replace` run the closest-enough pair becomes one `modified` row, the rest fall out as separate removals and additions | `0.60` |

Similarity is `difflib.SequenceMatcher` over the case-folded, stripped strings.

What the fallbacks buy:

- **A rename stays a rename.** The section id survives an edit to the heading;
  when the id does not survive (a re-import), the heading text still pairs, and
  failing that the slug `key` does.
- **A move stays a move.** Moved items are not "every item whose index
  changed": the longest run of pairs that kept their relative order is treated
  as stationary, and only the rest are `moved`. Without that, swapping two
  entries would report both as moved and inserting one entry would report
  everything below it as moved.
- **Structure changes are not text changes.** A section whose `kind` changed is
  rendered as its whole old content removed and its whole new content added,
  because the two shapes are not comparable leaf-for-leaf.

## The `DocumentDiff` shape

```jsonc
{
  "stats": {
    "sections_added": 0, "sections_removed": 0, "sections_renamed": 1,
    "sections_moved": 0,
    "entries_added": 0, "entries_removed": 0, "entries_modified": 2,
    "entries_moved": 1,
    "bullets_added": 3, "bullets_removed": 1, "bullets_modified": 4,
    "tags_added": 2, "tags_removed": 0,
    "total_changes": 14          // the sum of the counters above
  },
  "header": [ /* DiffRow[] — name, headline, one row per contact kind */ ],
  "sections": [
    {
      "status": "renamed",       // added | removed | renamed | modified | moved | unchanged
      "base_key": "experience", "head_key": "experience",
      "base_heading": "Experience", "head_heading": "Professional Experience",
      "base_index": 1, "head_index": 1,
      "rows": [
        {
          "kind": "bullet",      // entry | bullet | tag | group | text | line
          "status": "modified",  // added | removed | modified | moved | unchanged
          "path": "sections.experience.entries[0].bullets[2].text",
          "base_text": "Built APIs",
          "head_text": "Built ingest APIs serving 1M req/day",
          "spans": [{ "side": "head", "start": 6, "end": 13, "op": "insert" },
                    { "side": "head", "start": 17, "end": 36, "op": "insert" }],
          "anchor": { "section_id": "…", "section_key": "experience", "entry_id": "…", "index": 0 }
        }
      ]
    }
  ]
}
```

Details that matter when you consume it:

- **`sections` is in head order** (`head_index`, falling back to `base_index`
  for a removed section), so the list reads like the resulting document.
- **The header is not a section.** It is its own row list, with paths
  `header.name`, `header.headline` and `header.contacts[<kind>]` — contacts
  pair by `kind`, so a changed email is one `modified` row, not a delete plus an
  add.
- **`spans` are populated only on `modified` rows**, as character ranges into
  `base_text`/`head_text`. Tokenization keeps trailing whitespace, so the
  offsets index the original strings exactly and a renderer can slice them
  without re-tokenizing.
- **Section status precedence is `renamed` → `modified` → `moved` →
  `unchanged`**, while `sections_moved` counts a move even when the section also
  changed — the label tells you the most important thing that happened, the
  counters tell you everything that happened.
- **A section's own rows carry an entry header row** (`kind: "entry"`, text
  `title | subtitle | period`) followed by that entry's leaves, so an entry
  reads as a unit.
- **The counters are coarser than the row kinds.** A `text` section's prose and
  an entry's `summary` count in `bullets_modified`; tag and group values count
  in `tags_added`/`tags_removed`. Do not derive per-kind totals from them —
  count rows if you need that.
- **`context` trims unchanged rows**: the default keeps 2 unchanged rows around
  each change; `0` returns changes only. Trimming is per row list, so an
  entirely unchanged section still appears, with an empty or near-empty `rows`.

Row paths use the same grammar as the AI change paths
([front-end-apis.md](../apis/front-end-apis.md#ai-change-paths)) — section by
`key`, never by position — which is what lets a row be replayed as an accept.
A bracket index is the head-side position where the row exists on the head
side, and the base-side position otherwise.

## `POST /api/v1/diff`

Each side of a comparison is a **ref**, and the engine does not care which kind
produced the document — so resume-vs-resume, version-vs-version and
resume-vs-version are one endpoint
([`app/routers/diff.py`](../../../apps/backend/app/routers/diff.py)).

```jsonc
{
  "base": { "resume_id": "…" },   // exactly one of resume_id | version_id
  "head": { "version_id": "…" },  // exactly one of resume_id | version_id
  "mode": "document",             // "document" | "tex"
  "context": 2                    // 0–20
}
```

- `{ "resume_id": … }` resolves `resumes.processed_data`;
  `{ "version_id": … }` resolves that timeline entry's stored document. Both
  are projected through `migrate_document`, so a v1 row compares cleanly
  against a v2 one.
- **A ref with both fields or neither is a `422`** — the "exactly one" rule is
  a validator on the request model, not a runtime branch.
- **Both refs must resolve inside the active workspace** (`X-Workspace-Id`),
  otherwise `403`: a diff reads two documents at once, and workspaces are
  separate namespaces.
- An unknown `resume_id`/`version_id` is a `404` naming the missing id.
- `mode: "document"` returns a `DocumentDiff`. `mode: "tex"` returns
  `{ "rows": DiffRow[] }` — a line diff (`kind: "line"`, paths `tex[i]`) over
  the two sides' LaTeX sources, described in
  [latex-export.md](latex-export.md).

## Partial accept

`POST /resumes/improve/confirm` takes `accepted_paths: string[] | null`
(at most 2000 entries):

- **`null` (or omitted) accepts the whole proposal** — the default. The merge is
  skipped entirely and the proposal is confirmed as it was previewed.
- **An array takes only those paths.** `merge_accepted` deep-copies the source
  document and pulls in one leaf per accepted path; everything else stays at the
  source value. The result then goes back through the same preservation chain
  and confirm-payload validation as a whole preview, so a subset is held to the
  same contract.

Only **content leaves** are selectable, because that is all AI tailoring edits —
section and entry structure always comes from the source document:

| Selectable path | Granularity |
|---|---|
| `sections.<key>.text` | the prose block |
| `sections.<key>.entries[i].summary` | the entry's paragraph |
| `sections.<key>.entries[i].bullets[j].text` | one bullet |
| `sections.<key>.tags` | **the whole list** |
| `sections.<key>.groups[i].values` | **the whole list** |

The two list paths are all-or-nothing: every value row in a `tags` section
shares one path, so the UI dedupes them into a single checkbox. Short values
have no per-item provenance worth splitting.

Everything else — an entry header row, a group label, a header row — carries no
checkbox. The allowlist lives twice, once per side, and the two must agree:
`merge_accepted` in the engine and `SELECTABLE_PATHS` in
[`components/diff/paths.ts`](../../../apps/frontend/components/diff/paths.ts).

Resolution notes: sections are matched by `key` (a section whose `kind` changed
is skipped entirely), entries are looked up by `entry.id`, and an accepted
bullet the AI appended past the source's rows is appended with the style the
model authored. A path the merge cannot resolve changes nothing.

A bracket index in an accepted path is a position, and `merge_accepted` walks
positions in the **source** document while diff rows carry head-side positions.
On the tailoring path the two agree, because no AI change path can add, remove
or move an entry — `improver.build_allowed_paths` only ever admits an entry's
`summary` and `bullets`. Any new partial-accept surface has to hold to the same
rule.

## The three surfaces

All three render [`components/diff/`](../../../apps/frontend/components/diff):
`DiffView` (stats bar, unified/split toggle, one collapsible group per section),
`DiffRows` (a flat row list, with unchanged runs of 3+ rows collapsed behind an
expander), `DiffRowLine`, `DiffSectionGroup`, `DiffStatsBar`, and `paths.ts`.

| Surface | Where | Diff comes from |
|---|---|---|
| Tailor preview modal | `components/tailor/diff-preview-modal.tsx`, opened by `/tailor` | `ImproveResumeData.diff`, computed server-side during preview/confirm |
| Regenerate preview | `components/builder/regenerate-diff-preview.tsx`, in the builder's AI regenerate wizard | `RegeneratedItem.rows`, computed server-side by `diff_value_lists` |
| Compare page | `app/(default)/compare/page.tsx` | `POST /diff` via `lib/api/diff.ts` |

The tailor modal is the only surface that collects a selection: it passes
`onAcceptedPathsChange` to `DiffView`, which turns every selectable row into a
checkbox. Everything is ticked when the modal opens, and confirming with
everything still ticked sends `accepted_paths: null` rather than an exhaustive
list — so the ordinary "accept the tailoring" flow stays one click and sends the
simplest possible payload.

The regenerate preview reuses `DiffRows` directly rather than `DiffView`,
because it compares two lists rather than two documents: the rows arrive already
computed, so nothing re-derives a diff in the client.

The Compare page is linkable — `?base=<token>&head=<token>` where a token is
`resume:<id>` or `version:<id>` (`parseRefToken` / `formatRefToken` in
`lib/api/diff.ts`). A malformed token is a bad link, reported as such, not a
server round trip. Two entry points navigate there:

- **Dashboard** — tick exactly two resumes, then **Compare**
  (`?base=resume:<a>&head=resume:<b>`).
- **Version timeline** — the **Compare** button on a row
  (`?base=version:<id>&head=resume:<id>`), i.e. "what changed since this
  point", with the older version as base.

## Related

- [custom-sections.md](custom-sections.md) — why sections are data, and what
  `key`/`id` mean
- [preview-confirmation.md](preview-confirmation.md) — the preview identity and
  confirm transaction that partial accept plugs into
- [enrichment.md](enrichment.md) — the regenerate flow that produces
  `RegeneratedItem.rows`
- [front-end-apis.md](../apis/front-end-apis.md) — wire contracts
- [backend-guide.md](../architecture/backend-guide.md) — where the engine sits
  in the backend
