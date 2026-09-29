# Testing Strategy & Verification

> **Scope:** backend (`apps/backend`, pytest) and frontend (`apps/frontend`, vitest).
> **Gate:** `.github/workflows/tests.yml` on pushes to `main`/`dev` — both suites plus
> `tsc --noEmit` and eslint. Not `pull_request`, and there is no pre-push hook.

For opt-in provider settings and generated-result evaluation, see the
[eval harness](../../apps/backend/tests/evals/README.md).

---

## Deterministic tests vs evals

- **Deterministic test** — LLM mocked, asserts code behavior given a known response. Fast, runs
  on every change. Answers *"is the plumbing correct?"*
- **Eval** — real (or recorded) LLM call scored against a rubric. Non-deterministic, costs
  money/time, runs on demand, **never in the gate**. Answers *"did this prompt change make the
  output better?"*

You cannot answer "does my prompt change help?" with a deterministic test, and you should never
block a push on a non-deterministic eval. Both layers, kept separate: `pytest`'s `addopts` carry
`-m "not eval"`, so the default suite makes no network or LLM call.

---

## What "verify the work" means here

Three mechanisms, applied to every change:

1. **Coverage delta.** A batch reports before/after coverage for the modules it touches.
   Numbers, not vibes.
2. **Anti-theater check.** For a new test on critical logic, confirm it *fails when the code is
   broken* (a quick manual mutation). This is the antidote to the "passes for the wrong reason"
   trap.
3. **Regression tests that pin shipped behavior.** Examples already locked in:
   - `_normalize_api_base` — `/v1/v1` duplicate-path dedup, OpenAI preserved as-is.
   - `resolve_api_key` — `ollama`/`openai_compatible` must **not** fall back to the env
     `LLM_API_KEY`, so a paid key can't leak to a local server.
   - `get_model_name` — `ollama_chat/` prefix and OpenRouter nested prefixes.
   - Empty-extracted-text rejection on upload.
   - `restore_dates_from_markdown` — months survive LLM parsing.

---

## How to run

```bash
cd apps/backend

# Full deterministic suite (LLM-judge evals are auto-excluded via addopts -m "not eval")
uv run pytest

# Coverage (ephemeral plugin, no pyproject change)
uv run --with pytest-cov pytest -q --cov=app --cov-report=term-missing

# Generated-result quality evals on demand — explicitly configure provider
# environment settings as described in tests/evals/README.md before opting in.
# Test data remains isolated; developer databases/key stores are not imported.
RM_RUN_PAID_EVAL=1 uv run pytest tests/evals -m eval

# One module
uv run pytest tests/unit/test_parser.py -q
```

Backend layers: `tests/unit` (pure logic), `tests/service` (mocked LLM), `tests/integration`
(real routers over httpx ASGI, real temp SQLite), `tests/evals` (structural scorers plus the
gated judge).

---

## Frontend suite

`apps/frontend` uses **vitest + Testing Library (jsdom)**:

```bash
cd apps/frontend
npm run test        # vitest run
npx tsc --noEmit    # the only check that sees tests/ — next build does not
npm run lint
```

---

## Open question

Decide coverage floors per module once the I/O surface is broadly covered — a single global
percentage hides gaps.

---

## Agentic end-to-end monitor (on-demand, report-only)

Above the deterministic suites sits an **agentic E2E monitor** — an opt-in harness that drives
the *real* running app (master resume → 3–4 tailored variations → PDFs), captures a durable
evidence bundle (logs, every intermediate JSON, PDFs), and has a Claude Code skill judge it on
output quality, flow/render integrity and provider reality. It is a **report, never a gate**.

- Harness and how-to: `apps/backend/e2e_monitor/README.md`.
- Its deps are an optional extra (`uv sync --extra dev --extra e2e-monitor`), every move is
  gated behind `RM_E2E_MONITOR=1` plus a configured key, and the runnable skill is gitignored
  (its source is the committed `e2e_monitor/AGENT_PLAYBOOK.md`). The developer's real SQLite
  database is never touched (isolated `DATA_DIR`).
- Run: `cd apps/backend && RM_E2E_MONITOR=1 uv run python -m e2e_monitor sweep`, then
  `bash e2e_monitor/install_skill.sh` and invoke the `monitor-e2e` skill for the report.
