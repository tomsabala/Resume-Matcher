# Resume Enrichment Feature

> **AI-powered resume improvement with targeted questions.**

## Overview

The enrichment feature helps users improve their master resume with more detailed content by:

1. Analyzing the resume for weak/generic content
2. Asking targeted questions about their experience
3. Generating additional bullet points based on answers (the separate regenerate
   flow also rewrites short-value lists)

## How It Works

1. User clicks "Enhance Resume" on the master resume page
2. AI analyzes the resume and identifies weak/generic content
3. User answers targeted questions (max 6 questions total) about their experience
4. AI generates additional content based on user answers
5. New content is **added** to existing content (not replaced)

## Key Design Decisions

- **Maximum 6 questions**: To avoid overwhelming users, the AI generates at most 6 questions across all items
- **Additive enhancement**: Original content is preserved; new enhanced rows are appended after it
- **Question prioritization**: AI prioritizes the most impactful questions that will yield the best improvements
- **Section-agnostic**: nothing here enumerates resume sections. An item is an
  entry or a value list, wherever the user put it.

## Items: ids and types

Analysis, enhancement, regeneration and apply all address content through an
`item_id` + `item_type` pair. An item id is assembled from **stable ids**, not
from positions or headings:

| `item_type` | `item_id` | Addresses |
| ----------- | --------- | --------- |
| `entry` | `<section_key>:<entry_id>` | one entry of an `entries` section (`experience:3f1c9ab2…`) |
| `values` | `<section_key>:#tags` | the flat value list of a `tags` section (`languages:#tags`) |
| `values` | `<section_key>:#group:<index>` | one group's `values` in a `groups` section (`skills:#group:0`) |

`section_key` is `Section.key`; `entry_id` is `Entry.id`. Both are copied
verbatim out of the document — the analysis prompt is explicit that an id must
never be derived from a heading, from an entry's array position, or invented.
The resolvers (`_find_entry`, `_find_value_list` in
`apps/backend/app/routers/enrichment.py`) look the section up by key and the
entry up by id; an unresolvable id becomes an item error and is discarded
rather than applied to a best-guess target.

This is why ids are built this way: an `entry_id` is stable for the entry's
life, so a user reordering entries (or sections) between analysis, preview and
apply cannot silently retarget a different entry. A positional id would.

Each item also carries `section_heading`, a display-only field holding the
owning section's heading (falling back to its key) so the wizard can label an
item with the user's own section name. `item_type` — not a section name — is
what the backend dispatches on:

| Apply endpoint | `entry` | `values` |
| --- | --- | --- |
| `/enrichment/apply` (enhancement) | appends the new rows to `entry.bullets` | resolves entries only — an unresolvable item is logged and skipped |
| `/enrichment/apply-regenerated` | replaces `entry.bullets`, carrying each row's existing `style` over by position | replaces `section.tags` or the group's `values` |

`apply-regenerated` is all-or-nothing: every item's `original_content` must
still match what is stored, or the whole request returns `409` and the user
regenerates. Both apply paths write through the resume-version funnel
(`origin="ai_enrich"`), so an enrichment the user dislikes can be restored away
from.

### The regenerate preview is a diff

A `RegeneratedItem` carries `original_content`, `new_content` and **`rows`** —
`DiffRow`s the server computes with `document_diff.diff_value_lists`, word-level
spans included. The wizard renders them with the shared `DiffRows` component, so
the regenerate preview and the tailoring diff look and behave the same and the
client never re-derives a comparison. See
[document-diff.md](document-diff.md).

## Key Files

| File                                           | Purpose                                 |
| ---------------------------------------------- | --------------------------------------- |
| `apps/backend/app/prompts/enrichment.py`       | AI prompts for analysis, enhancement and regeneration (including the item-id rules) |
| `apps/backend/app/routers/enrichment.py`       | API endpoints + the item-id resolvers   |
| `apps/backend/app/schemas/enrichment.py`       | `EnrichmentItem`, `EnhancedDescription`, `Regenerate*` — `item_id` / `item_type` / `section_heading` |
| `apps/frontend/lib/api/enrichment.ts`          | Client mirror of those schemas          |
| `apps/frontend/hooks/use-enrichment-wizard.ts` | React state management for wizard flow  |
| `apps/frontend/components/enrichment/*.tsx`    | UI components for enrichment modal      |

## API Endpoints

| Endpoint                                        | Description                                 |
| ----------------------------------------------- | ------------------------------------------- |
| `POST /enrichment/analyze/{resume_id}`          | Analyze resume and generate questions       |
| `POST /enrichment/enhance`                      | Generate enhanced content from answers      |
| `POST /enrichment/apply/{resume_id}`            | Apply enhancements to resume                |
| `POST /enrichment/regenerate`                   | Rewrite selected items from an instruction  |
| `POST /enrichment/apply-regenerated/{resume_id}`| Apply regenerated items to resume           |

## Failure and retry boundaries

Enhancement generation returns `enhancements` and per-item `errors`; an entirely failed attempt returns an error instead of an empty success. The preview names failed items and allows applying the successful items. Failed items retain their original content. Analysis and replacement services validate AI result structure before returning it.

A final-prompt size rejection while generating one item is an item error: successful items before or after it remain applicable, and the failed item asks the user to shorten its description or answers. If no item succeeds and a prompt is oversized, the request remains HTTP 422. Request/source bounds and the shared legacy analysis stage also remain request-wide errors. The total POST deadline is different: it cancels the operation and returns HTTP 504 even after earlier items completed. That expired operation does not return an actionable partial preview.

The wizard hook owns one resume and one active attempt. Reset, unmount and resume changes invalidate old results. Apply failure returns to the same preview with its failed-item notice. After apply succeeds, the viewer owns a separate refresh: a failure keeps the saved acknowledgement visible and Retry fetches the resume without applying it again. Closing the modal or changing resume identity invalidates late refresh results. These contracts are tested through the actual hooks, viewer/modal and preview components in `apps/frontend/tests/wizard-hook-lifecycle.test.tsx`, `apps/frontend/tests/resume-viewer-enrichment-lifecycle.test.tsx` and `apps/frontend/tests/enrichment-preview-errors.test.tsx`.

See [AI operation budgets](../architecture/ai-operation-budgets.md) for collection limits, bounded regeneration concurrency and the shared POST deadline.
