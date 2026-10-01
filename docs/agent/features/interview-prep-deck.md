# Interview Prep Deck Feature

> **A workspace-global deck of interview questions: technical cards are studied as a flip-card game, personal cards are rehearsed with LLM feedback.**

## Overview

The Interview Prep Deck (`/interview-prep`) is a top-level page alongside
dashboard, tracker and settings. A card is a question plus a back containing an
LLM-authored model answer, an explanation and examples. Cards come in two
categories:

- **`technical`** — studied in a flip-card dialog: reveal the back, then rate
  it Again / Good / Easy.
- **`personal`** — questions about the owner, their resume and their history.
  Rehearsed in an editable list: the owner writes their own answer and asks the
  LLM to critique it.

Cards are created by hand, generated from the master resume, or imported from
the per-resume **INTERVIEW PREP** builder tab via its "Send to deck" action.
Every generation path shows a review-before-save step.

## Naming: not `interview_prep`

`interview_prep` is the **per-resume builder tab** — a `Resume.interview_prep`
column, `InterviewPrepData`, `app/services/interview_prep.py`,
`POST /resumes/{id}/generate-interview-prep` and the `enable_interview_prep`
flag. That feature is untouched; it only gained an outbound "Send to deck"
button.

This feature is `prep_cards` everywhere: the `prep_cards` table, `PrepCard`,
`app/schemas/prep_cards.py`, `app/routers/prep_cards.py`,
`app/services/prep_cards.py`, `lib/api/prep-cards.ts`, `components/prep/`, and
the `prepDeck` copy root.

The split matters at the LLM boundary: `app/llm.py` has a truncation-detection
branch keyed on `schema_type == "interview_prep"` and the key set
`{role_fit_analysis, resume_questions, project_follow_ups, skill_gaps,
talking_points}`. Passing that `schema_type` with a different payload shape
makes every response look truncated and burns retries, so the three prep-card
calls pass `"prep_card_generate"`, `"prep_card_answer"` and
`"prep_card_critique"` — unknown to those branches, which is the intended
default path.

There is **no feature flag**. The page is always reachable; with no provider
configured the three LLM endpoints fail with the standard 500/503/504, exactly
like cover-letter generation.

## Data Model

`PrepCard` (SQLite, `apps/backend/app/models.py`; migration
`0009_prep_cards`): `card_id` (PK), `workspace_id`, `category`
(`technical`/`personal`), `question`, `answer`, `explanation`, `examples`
(JSON), `my_answer`, `critique` (JSON), `confidence`
(`unrated`/`again`/`good`/`easy`), `source` (`manual`/`generated`/`imported`),
`application_id` (optional tracker link for job-specific grounding),
`reviewed_at`, `created_at`, `updated_at`.

`reviewed_at` is written by exactly one rule, in `Database.update_prep_card`: a
PATCH that carries `confidence` stamps it. A rating *is* the review event;
nothing else sets that column. There is no scheduling algorithm — the rating is
a manual three-way label, not an SRS interval.

`PrepCard` is registered in both workspace-cascade tuples
(`_delete_workspace_rows` and `reset_workspace`), so deleting or resetting a
workspace takes its cards with it.

## How It Works

1. **Manual add:** `POST /prep-cards` with a question and optional answer
   (`source="manual"`).
2. **Generate:** `POST /prep-cards/generate` grounds on the workspace's master
   resume (400 when there is none) plus, when `application_id` is supplied, the
   linked tracker application's job description. It returns **proposals and
   persists nothing**; the user accepts a reviewed subset through
   `POST /prep-cards/bulk-create` (`source="generated"`). The requested
   category is forced onto every proposal — the model is told which kind of
   question to ask, but its echo of that choice is never trusted.
3. **Answer:** `POST /prep-cards/{id}/answer` authors the back of a card and
   stores `answer`/`explanation`/`examples`.
4. **Critique:** `POST /prep-cards/{id}/critique` stores the owner's own answer
   and the LLM's verdict (`score` 1-5, `strengths`, `gaps`,
   `suggested_rewrite`).
5. **Send to deck:** the builder's INTERVIEW PREP tab maps its generated
   payload into proposals with the pure mapper
   `components/prep/proposals.ts`: `resume_questions` and `project_follow_ups`
   become **personal** cards; `skill_gaps` become **technical** ones;
   `role_fit_analysis` and `talking_points` are not questions and are not
   imported. Imported cards keep `answer` null — `suggested_answer_points` are
   preparation hints, not an answer — so the back still offers
   "Generate answer".

A deleted application or job degrades to no job context rather than erroring:
the card still works, it just loses job-specific grounding.

## API (`prefix=/prep-cards`, mounted under `/api/v1`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/prep-cards` | All cards, newest first; `?category=` filters |
| POST | `/prep-cards` | Create one card by hand |
| POST | `/prep-cards/bulk-create` | Accept a reviewed batch of proposals |
| POST | `/prep-cards/bulk-delete` | Delete many cards |
| POST | `/prep-cards/generate` | Propose questions; persists nothing |
| GET | `/prep-cards/{id}` | One card |
| POST | `/prep-cards/{id}/answer` | Author and store the back of a card |
| POST | `/prep-cards/{id}/critique` | Store the owner's answer + its critique |
| PATCH | `/prep-cards/{id}` | Update question/answer/category/confidence/own answer |
| DELETE | `/prep-cards/{id}` | Delete one card |

The router uses `route_class=AIOperationRoute`, so the three LLM POSTs inherit
the request deadline and the `PromptSizeError` → 422 / `TimeoutError` → 504
mappings. It is a no-op for the CRUD verbs.

## Prompts

Three templates in `app/prompts/templates.py`, exported from `app/prompts`:
`PREP_CARD_GENERATE_PROMPT`, `PREP_CARD_ANSWER_PROMPT` and
`PREP_CARD_CRITIQUE_PROMPT`. Each opens with `IMPORTANT: Write in
{output_language}.` and carries the same no-fabrication guardrails as
`INTERVIEW_PREP_PROMPT`. They are not user-overridable, so they are absent from
`REQUIRED_FEATURE_PROMPT_PLACEHOLDERS` and `_FEATURE_PROMPT_KEYS`.

Prompt inputs are bounded by `app/services/prompt_bounds.py`
(`truncate_text_for_prompt`, `truncate_json_value`,
`serialize_resume_data_for_prompt`) — extracted from `interview_prep.py` when
this second consumer appeared, and shared by both services.

## Key Files

| File | Purpose |
|------|---------|
| `apps/backend/app/models.py` | `PrepCard` ORM model |
| `apps/backend/migrations/versions/0009_prep_cards.py` | Table + indexes |
| `apps/backend/app/schemas/prep_cards.py` | Request/response schemas, category/confidence enums |
| `apps/backend/app/routers/prep_cards.py` | The deck endpoints |
| `apps/backend/app/services/prep_cards.py` | The three LLM calls |
| `apps/backend/app/services/prompt_bounds.py` | Shared prompt-input bounds |
| `apps/backend/app/database.py` | Facade CRUD/bulk methods + both cascade tuples |
| `apps/frontend/app/(default)/interview-prep/page.tsx` | Route |
| `apps/frontend/components/prep/prep-deck.tsx` | Stateful container (the only fetcher) |
| `apps/frontend/components/prep/study-dialog.tsx` | Flip-card game + rating |
| `apps/frontend/components/prep/personal-dialog.tsx` | Rehearsal + critique |
| `apps/frontend/components/prep/card-form-dialog.tsx` | Add/edit |
| `apps/frontend/components/prep/proposal-review-dialog.tsx` | Review-before-save (generate + import) |
| `apps/frontend/components/prep/proposals.ts` | Pure builder-prep → proposal mapper |
| `apps/frontend/lib/api/prep-cards.ts` | Typed API client |
| `apps/frontend/components/common/{bottom-nav,app-header}.tsx` | The two navigations (exact complements) |

The card faces swap instantly: the design system forbids animated transitions,
so there is no CSS 3D flip.

## Tests

- Backend: `tests/integration/test_prep_cards_api.py` (CRUD round trip,
  category filter, the `reviewed_at` rule, 404s, bulk create/delete, workspace
  isolation, generate-persists-nothing, answer/critique persistence, the
  no-master-resume 400s), `tests/unit/test_prep_cards_service.py`
  (`schema_type`/`max_tokens` per call, forced category, count truncation,
  prompt bounding, malformed-JSON rejection),
  `tests/integration/test_ai_operation_budgets.py::test_prep_card_ai_failures_reach_api_boundary`
  (504/422 mappings).
- Frontend: `tests/prep-deck.test.tsx` (category filter, rating advances the
  study dialog, personal cards open the rehearsal dialog),
  `tests/prep-proposals.test.ts` (the import mapping),
  `tests/api-prep-cards.test.ts` (client payloads/URLs),
  `tests/bottom-nav.test.tsx` (the `/interview-prep` tab).
