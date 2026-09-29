# Resume Matcher Setup Guide

Everything needed to run this fork locally or in Docker.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Backend setup](#backend-setup)
- [Frontend setup](#frontend-setup)
- [Provider configuration](#provider-configuration)
- [Docker](#docker)
- [Accessing the application](#accessing-the-application)
- [Command reference](#command-reference)
- [Environment variables](#environment-variables)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)
- [Testing and CI](#testing-and-ci)

---

## Prerequisites

| Tool | Minimum | Check |
|---|---|---|
| Python | 3.13+ | `python --version` |
| Node.js | 22+ | `node --version` |
| npm | 10+ | `npm --version` |
| uv | latest | `uv --version` |
| Git | any | `git --version` |

Installing uv:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or via pip
pip install uv
```

---

## Backend setup

```bash
cd apps/backend
cp .env.example .env
```

A minimal working `.env`:

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-5-nano-2025-08-07
LLM_API_KEY=sk-your-api-key-here

# REQUIRED — the backend refuses to start without it.
# single = private instance, no authentication: anyone who can reach the port
# owns the data. Correct on your own machine, wrong on a shared host.
TENANT_MODE=single

HOST=0.0.0.0
PORT=8000
FRONTEND_BASE_URL=http://localhost:3030
CORS_ORIGINS=["http://localhost:3030","http://127.0.0.1:3030"]
```

Then:

```bash
uv sync --extra dev                  # dev deps live in [project.optional-dependencies]
uv run playwright install chromium   # required by every PDF endpoint
uv run alembic upgrade head          # Alembic owns the schema
uv run uvicorn app.main:app --reload --port 8000
```

`RELOAD=true uv run app` is the equivalent using the project's own entry point.

The SQLite database, the encrypted API-key store and the Fernet secret all live in
`apps/backend/data/` and are git-ignored.

---

## Frontend setup

```bash
cd apps/frontend
cp .env.sample .env.local   # optional; every value has a working default
npm install
npm run dev                 # http://localhost:3030
```

Port 3030 comes from `-p 3030` in the `dev` script, not from the environment. Next reads `PORT`
when it parses argv and the backend reads `PORT` too, so never export `PORT` shell-wide for both
processes — change the port with `npm run dev -- -p 3001` and update `FRONTEND_BASE_URL` and
`CORS_ORIGINS` in the backend `.env` to match.

---

## Provider configuration

Set these in `apps/backend/.env`, or in the Settings UI at
<http://localhost:3030/settings> (which stores keys encrypted in SQLite).

| `LLM_PROVIDER` | Example `LLM_MODEL` | `LLM_API_BASE` |
|---|---|---|
| `openai` | `gpt-5-nano-2025-08-07` | — |
| `openai_compatible` | `llama-3.1-8b` | `http://localhost:8080/v1` (llama.cpp, vLLM, LM Studio; key optional) |
| `azure_foundry` | `mistral-large-latest` | `https://<resource>.services.ai.azure.com/models` |
| `anthropic` | `claude-haiku-4-5-20251001` | — |
| `openrouter` | `deepseek/deepseek-chat` | — |
| `gemini` | `gemini/gemini-3-flash-preview` | — |
| `deepseek` | `deepseek-chat` | — |
| `groq` | `llama-3.3-70b-versatile` | — |
| `ollama` | `gemma3:4b` | `http://localhost:11434` |

### Ollama

```bash
ollama pull gemma3:4b
ollama serve
```

```env
LLM_PROVIDER=ollama
LLM_MODEL=gemma3:4b
LLM_API_BASE=http://localhost:11434
# LLM_API_KEY is not needed
```

From Docker, point at the host instead: `LLM_API_BASE=http://host.docker.internal:11434`
(macOS/Windows; on Linux use the host IP).

---

## Docker

```bash
docker compose up -d      # start
docker compose logs -f    # follow logs
docker compose down       # stop
```

Host port comes from `PORT` in the **root** `.env` (default 3030) and maps to container port
3000. `PORT=4000 docker compose up -d` moves it.

### LaTeX export

The image ships [Tectonic](https://tectonic-typesetting.github.io/) (~30 MB plus a pre-warmed
package bundle) so the LaTeX tab can compile PDFs in-container. It is a **build arg**, decided
at image build time:

```bash
docker compose build                        # default: INSTALL_LATEX=true
INSTALL_LATEX=false docker compose build     # smaller image, no TeX engine
```

Without an engine — or on an architecture other than amd64/arm64 — generation, editing, reset
and `.tex` download all still work; only the in-container compile answers `503`. Pin an engine
with `RESUME_MATCHER_LATEX_ENGINE` instead of the `tectonic` → `latexmk` → `xelatex` →
`pdflatex` auto-detection.

### Tenancy

`TENANT_MODE` is required in the container too. `single` means no authentication: **anyone who
can reach the port owns the data**. `header` expects a gateway that authenticates visitors and
injects `X-Apps-Tenant`, `X-Apps-Role` and `X-Apps-Proxy-Secret`, and refuses to start unless
`GATEWAY_SECRET` matches what the gateway sends.

### Secrets

Any of `LOG_LEVEL`, `LOG_LLM`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_API_BASE` can be
supplied as a `*_FILE` variant pointing at a mounted Docker secret:

```bash
LLM_API_KEY_FILE=/run/secrets/llm_api_key docker compose up -d
```

Use the variable or its `*_FILE` variant, never both — the container exits with an explicit
error if both are set.

### Logging

```bash
LOG_LEVEL=INFO LOG_LLM=DEBUG docker compose up -d
```

> **Security warning:** `LOG_LLM=DEBUG` makes LiteLLM log API keys in plaintext. The default
> `WARNING` is safe. Changes to either level need a container restart.

---

## Accessing the application

| URL | Description |
|---|---|
| <http://localhost:3030> | Dashboard |
| <http://localhost:3030/settings> | Provider, keys, features |
| <http://localhost:3030/api/v1/health> | Backend health check |
| <http://localhost:3030/docs> | Interactive API docs |

First run: open Settings, select a provider, enter the API key (or configure Ollama), save,
then "Test Connection". Upload a resume from the Dashboard, or build one at `/resume-wizard`.

---

## Command reference

### Backend (`cd apps/backend`)

```bash
RELOAD=true uv run app                       # dev server with auto-reload
uv run uvicorn app.main:app --port 8000      # plain server
uv sync --extra dev                          # install deps incl. test deps
uv run pytest                                # test suite (LLM-judge evals excluded)
uv run pytest --cov=app                      # with coverage
uv run alembic upgrade head && uv run alembic check   # migrate, then verify models match
RM_E2E_MONITOR=1 uv run python -m e2e_monitor sweep   # opt-in end-to-end monitor
```

### Frontend (`cd apps/frontend`)

```bash
npm run dev        # dev server on :3030
npm run build      # production build
npm run start      # serve the build
npm run lint       # eslint
npm run typecheck  # tsc --noEmit
npm run format     # prettier --write
npm run test       # vitest
```

---

## Environment variables

From `apps/backend/.env.example`:

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `openai` | See the provider table above |
| `LLM_MODEL` | — | Provider-specific model id |
| `LLM_API_KEY` | — | Optional for `ollama` and most `openai_compatible` servers |
| `LLM_API_BASE` | — | Required for `ollama`, `openai_compatible`, `azure_foundry` |
| `TENANT_MODE` | — | **Required.** `single` or `header` |
| `GATEWAY_SECRET` | — | Required when `TENANT_MODE=header` |
| `CLAIM_TENANT_REF` | — | One-shot ownership transfer when moving `single` → `header`; remove after one start |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Backend bind address |
| `RELOAD` | `false` | `true` makes `uv run app` auto-reload (dev only) |
| `REASONING_EFFORT` | — | `minimal`/`low`/`medium`/`high`; dropped for providers that don't support it |
| `LOG_LEVEL` | `INFO` | Application + Uvicorn |
| `LOG_LLM` | `WARNING` | LiteLLM; `DEBUG` logs API keys in plaintext |
| `FRONTEND_BASE_URL` | `http://localhost:3030` | Where the PDF renderer loads the print route from |
| `CORS_ORIGINS` | `["http://localhost:3030", ...]` | JSON array |
| `REQUEST_TIMEOUT_SECONDS` | `240` | Bounded to [30, 1800] |

`REQUEST_TIMEOUT_SECONDS` must be kept in step with the frontend's
`NEXT_PUBLIC_REQUEST_TIMEOUT_MS` (= this × 1000). The Next.js proxy and the browser client abort
on the shorter of the two, so raising only the backend has no effect.

---

## Troubleshooting

### Backend won't start

- **`TENANT_MODE` missing or misspelled** — the settings layer refuses a blank or unknown value.
  Set `TENANT_MODE=single` for local use.
- **`ModuleNotFoundError`** — run through uv: `uv run uvicorn app.main:app --reload`.
- **`LLM_API_KEY not configured`** — the `.env` has no valid key for the chosen provider.

### Frontend won't start

- **`ECONNREFUSED` when loading pages** — the backend isn't running.
- **Build or TypeScript errors** — clear the Next cache: `rm -rf apps/frontend/.next`.

### PDF download fails

`Cannot connect to frontend for PDF generation` means the backend can't reach the print route.
Check the frontend is running, and that `FRONTEND_BASE_URL` and `CORS_ORIGINS` name its actual
URL. On port 3001:

```env
FRONTEND_BASE_URL=http://localhost:3001
CORS_ORIGINS=["http://localhost:3001", "http://127.0.0.1:3001"]
```

### Non-Latin text renders as boxes (□□□) in the PDF

An uploaded resume can carry a non-Latin name, employer or school. The PDF is rendered by
headless Chromium, which falls back to **system** fonts for any glyph the bundled webfonts don't
cover, and a headless Linux host usually ships none for CJK.

Docker users: nothing to do, the image installs `fonts-noto-cjk`. Without Docker, install system
CJK fonts on the machine running the backend and restart it:

```bash
# Debian / Ubuntu
sudo apt-get install -y fonts-noto-cjk

# Fedora / RHEL
sudo dnf install -y google-noto-sans-cjk-fonts

# Arch
sudo pacman -S noto-fonts-cjk

# macOS — CJK fonts ship with the OS
```

### LaTeX export fails

- **`No LaTeX engine found …` (503)** — no TeX engine visible to the backend. Use **Download
  .tex** and compile elsewhere, rebuild the image with `INSTALL_LATEX=true`, or install Tectonic
  or a TeX distribution so `tectonic`/`latexmk`/`xelatex`/`pdflatex` is on `PATH`.
- **`LaTeX compilation failed` with an engine log (422)** — the engine ran and rejected a
  hand-edited source. Fix the line the log points at, or use **Reset to generated**; the edited
  version stays in version history either way.

### Ollama connection fails

`Connection refused to localhost:11434` — check `ollama list`, start `ollama serve`, and make
sure the model is pulled (`ollama pull gemma3:4b`).

---

## Project structure

```
apps/
├── backend/                 # FastAPI + Python
│   ├── alembic.ini          # Alembic config (Alembic owns the schema)
│   ├── migrations/          # env.py + versions/
│   ├── app/
│   │   ├── main.py          # Entry point
│   │   ├── config.py        # Environment settings
│   │   ├── database.py      # Async SQLAlchemy/SQLite facade
│   │   ├── models.py        # ORM models
│   │   ├── db_engine.py     # Async + sync SQLite engines (WAL/FK pragmas)
│   │   ├── crypto.py        # Fernet encrypt/decrypt for API keys at rest
│   │   ├── deps.py          # resolve_workspace_id (X-Workspace-Id header)
│   │   ├── llm.py           # LiteLLM wrapper
│   │   ├── latex/           # LaTeX export (escape/render/compile + *.tex.j2)
│   │   ├── routers/         # API endpoints (incl. applications.py = tracker)
│   │   ├── services/        # Business logic
│   │   ├── schemas/         # Pydantic models — document.py = the resume contract
│   │   └── prompts/         # LLM prompt templates
│   └── data/                # resume_matcher.db + encrypted API keys + .secret_key
│
└── frontend/                # Next.js + React
    ├── app/                 # Pages (dashboard, builder, wizard, tailor, tracker,
    │                        #   resumes/[id], settings, print)
    ├── components/          # UI (resume/section-kinds/, builder/forms/, tracker/, ...)
    ├── lib/                 # API client, types/document.ts, utils/
    ├── hooks/               # Custom React hooks
    └── messages/            # en.json — the sole UI copy bundle
```

---

## Testing and CI

```bash
cd apps/backend  && uv run pytest    # backend suite
cd apps/frontend && npm run test     # frontend suite
```

`.github/workflows/tests.yml` runs both on pushes to `main` and `dev`, plus `tsc --noEmit` and
eslint on the frontend. There is no pre-push hook and no PR-triggered workflow — CI on those two
branches is the whole gate.
