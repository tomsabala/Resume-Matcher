# Resume Matcher

A personal fork of [srbhr/Resume-Matcher](https://github.com/srbhr/Resume-Matcher), reshaped
around one owner running it for their own job search.

Keep one master resume. Paste a job description. The app proposes targeted edits, shows them
as a reviewable diff, and exports the result as a PDF or a LaTeX source you can hand-edit.

## What it does

- **Master resume** (`/builder`) — upload a PDF or DOCX, parsed into a typed `ResumeDocument`;
  per-section forms, drag-and-drop reordering, template picker.
- **Resume wizard** (`/resume-wizard`) — AI-led, one question at a time, builds a master resume
  from scratch.
- **Tailoring** (`/tailor`) — paste a job description, get a diff preview with per-row accept,
  then confirm.
- **Version history and compare** (`/compare`, `/resumes/[id]`) — every AI write is versioned;
  structured diff between any two documents or versions.
- **Application tracker** (`/tracker`) — Kanban board with drag/drop and bulk operations.
- **Workspaces** — named owner profiles scoping resumes, jobs and tracker entries, selected via
  the `X-Workspace-Id` header.
- **Cover letter, outreach message, interview prep** — opt-in, off by default, toggled in
  Settings.
- **Export** — PDF via headless Chromium, plus LaTeX export with a `.tex` source you can edit
  and recompile.
- **Providers** — `openai`, `openai_compatible`, `azure_foundry`, `anthropic`, `openrouter`,
  `gemini`, `deepseek`, `groq`, `ollama`. Configured in Settings or `.env`; API keys are stored
  Fernet-encrypted in SQLite, never in plaintext config.

The UI and all generated content are English.

## Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI, Python 3.13+, LiteLLM |
| Frontend | Next.js 16, React 19, Tailwind CSS v4 |
| Database | SQLite via async SQLAlchemy 2 + aiosqlite; schema owned by Alembic |
| PDF | Headless Chromium (Playwright) |

## Prerequisites

Python 3.13+, Node.js 22+, [uv](https://docs.astral.sh/uv/getting-started/installation/), Git.

## Quick start

```bash
git clone https://github.com/tomsabala/Resume-Matcher.git
cd Resume-Matcher

# Backend — terminal 1
cd apps/backend
cp .env.example .env            # set LLM_PROVIDER / LLM_MODEL / LLM_API_KEY, keep TENANT_MODE=single
uv sync --extra dev
uv run playwright install chromium
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# Frontend — terminal 2
cd apps/frontend
npm install
npm run dev                     # http://localhost:3030
```

Then open <http://localhost:3030/settings> to pick a provider and test the connection.

Docker instead: `docker compose up -d`, then <http://localhost:3030>.

Full instructions, provider tables, Docker options and troubleshooting: [SETUP.md](SETUP.md).
