# Resume Matcher — Agent Documentation Index

> Project-specific reference for agents working in the Resume Matcher codebase.

Generic, reusable guides (Swiss design system, Next.js performance) live in [`../portable/`](../portable/README.md) as standalone packs that can be lifted out of this repo and dropped into any project. This index covers only the docs that are tied to Resume Matcher itself.

## Quick Navigation

### Core docs

| Doc                                             | Purpose                       |
| ----------------------------------------------- | ----------------------------- |
| [quickstart](quickstart.md)                     | Install, run, test commands   |
| [coding-standards](coding-standards.md)         | Frontend/backend conventions  |
| [testing-strategy](testing-strategy.md)         | How the suites are run and kept honest |
| [backlog](backlog.md)                           | Deferred work (issues are off) |

### Architecture

| Doc                                                              | Purpose                                                         |
| ---------------------------------------------------------------- | --------------------------------------------------------------- |
| [backend-architecture](architecture/backend-architecture.md)     | Backend modules, API, services                                  |
| [backend-guide](architecture/backend-guide.md)                   | Module-by-module backend tour                                   |
| [frontend-architecture](architecture/frontend-architecture.md)   | Components, pages, state                                        |
| [frontend-workflow](architecture/frontend-workflow.md)           | User flows in the frontend                                      |
| [ai-operation-budgets](architecture/ai-operation-budgets.md)     | End-to-end deadlines, collection/source limits and cancellation |
| [storage-transactions](architecture/storage-transactions.md)     | Atomic master, job and tracker writes                           |

### APIs

| Doc                                                  | Purpose                         |
| ---------------------------------------------------- | ------------------------------- |
| [front-end-apis](apis/front-end-apis.md)             | API contract                    |
| [api-flow-maps](apis/api-flow-maps.md)               | Request/response flows          |
| [backend-requirements](apis/backend-requirements.md) | Backend behavioral requirements |

### Design (Resume Matcher specifics)

| Doc                                                                          | Purpose                           |
| ---------------------------------------------------------------------------- | --------------------------------- |
| [template-system](design/template-system.md)                                 | Resume template architecture      |
| [pdf-template-guide](design/pdf-template-guide.md)                           | PDF rendering pipeline            |

> **For the design system itself** (colors, components, anti-patterns), see the portable pack: [`../portable/swiss-design-system/`](../portable/swiss-design-system/README.md)

### Features

| Doc                                                            | Purpose                                                  |
| -------------------------------------------------------------- | -------------------------------------------------------- |
| [custom-sections](features/custom-sections.md)                 | The resume document: section kinds, keys, headings, visibility, column |
| [document-diff](features/document-diff.md)                     | The one diff engine: pairing rules, `POST /diff`, partial accept |
| [resume-templates](features/resume-templates.md)               | Template types and controls                              |
| [adding-resume-templates](features/adding-resume-templates.md) | How to add a new template                                |
| [latex-export](features/latex-export.md)                       | LaTeX render target: `.tex` generation, hand-edit override, compile |
| [enrichment](features/enrichment.md)                           | AI enrichment flow                                       |
| [jd-match](features/jd-match.md)                               | Job description matching                                 |
| [preview-confirmation](features/preview-confirmation.md)       | Durable preview identity, atomic confirmation and replay |
| [multi-tenancy](features/multi-tenancy.md)                     | Tenant modes, gateway headers, workspace ownership       |
| [application-tracker](features/application-tracker.md)         | Kanban tracker: columns, cards, bulk operations          |

### LLM Integration

| Doc                                   | Purpose                       |
| ------------------------------------- | ----------------------------- |
| [llm-integration](llm-integration.md) | Multi-provider AI via LiteLLM |

### Portable packs (live outside this folder)

| Pack                                                             | Purpose                                                                   |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------- |
| [swiss-design-system](../portable/swiss-design-system/README.md) | Full Swiss style design system — required reading for frontend work       |
| [nextjs-performance](../portable/nextjs-performance/README.md)   | Next.js 15 performance optimizations — required reading for frontend work |

## Project Structure

```
apps/
├── backend/                 # FastAPI + Python
│   ├── app/
│   │   ├── main.py          # Entry point
│   │   ├── routers/         # API endpoints
│   │   ├── services/        # Business logic
│   │   └── prompts/         # LLM templates
│   └── data/                # Database storage
│
└── frontend/                # Next.js + React
    ├── app/                 # Pages
    ├── components/          # UI components
    └── lib/                 # Utilities, API client
```

## How to Use

**New tasks:** Read `quickstart` → `coding-standards`

**Backend changes:** `backend-architecture` → `front-end-apis` → `llm-integration`

**Frontend changes:** `frontend-architecture` → portable [`swiss-design-system`](../portable/swiss-design-system/README.md) → portable [`nextjs-performance`](../portable/nextjs-performance/README.md) → `coding-standards`

**Template/PDF changes:** `pdf-template-guide` → `template-system` (Chromium HTML target); `latex-export` for the LaTeX target
