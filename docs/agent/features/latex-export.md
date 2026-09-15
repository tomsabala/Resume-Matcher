# LaTeX Export

> **A real `.tex` generated from the resume document, hand-editable, and compiled to PDF when the host has an engine.**

## Two render targets, one document

PDF export now has **two independent renderers**. Both consume the same
`ResumeDocument`; neither replaces the other.

| Target | Endpoint | Renderer | Template ids |
| ------ | -------- | -------- | ------------ |
| **Chromium HTML** | `GET /api/v1/resumes/{id}/pdf` | Headless Chromium over the Next.js print route, via Playwright | `swiss-single`, `swiss-two-column`, `modern`, `modern-two-column`, `latex`, `clean`, `vivid` |
| **LaTeX** | `GET /api/v1/resumes/{id}/tex/pdf` | A TeX engine on the host (`tectonic`/`latexmk`/`xelatex`/`pdflatex`) | `tex-classic`, `tex-compact` |

> **Naming trap.** `latex` in the first row is an **HTML** template
> (`apps/frontend/components/resume/resume-latex.tsx`) — a web layout that
> *looks* like LaTeX output and is rendered by Chromium. It has nothing to do
> with this feature. The LaTeX export templates are the `tex-`prefixed ids and
> live in `apps/backend/app/latex/templates/`. In prose: **"the `latex` HTML
> template"** vs **"the LaTeX export"**.

The Chromium path is documented in
[pdf-template-guide.md](../design/pdf-template-guide.md) and
[template-system.md](../design/template-system.md); its controls are in
[resume-templates.md](resume-templates.md).

## The document stays canonical

`resumes.tex_source` is the only extra state, and it is nullable:

| `tex_source` | What `GET /resumes/{id}/tex` serves | Follows document edits |
| ------------ | ----------------------------------- | ---------------------- |
| `NULL` (**generated**) | Fresh render of `processed_data` through the chosen template | Yes — every read re-renders |
| non-null (**override**) | The stored string, verbatim | No — the document no longer drives the `.tex` |

Nothing caches generated source: a save to the document changes the next
`GET`'s output with no invalidation step. `is_override` travels on every
response so the UI can state which of the two states it is in rather than
implying it.

## Escaping is the boundary (`app/latex/escape.py`)

`escape_tex` is the security and correctness boundary. Every user-authored
string crosses it; template macros never do. Without it `100% off` comments
out the rest of the line, and an `\input{/etc/passwd}` in a job title is a
file read.

| Input | Output |
| ----- | ------ |
| `\` | `\textbackslash{}` |
| `{` `}` | `\{` `\}` |
| `$` `&` `#` `_` `%` | `\$` `\&` `\#` `\_` `\%` |
| `^` | `\textasciicircum{}` |
| `~` | `\textasciitilde{}` |

**Backslash is escaped first.** Every other replacement *introduces*
backslashes, so handling `\` last would re-escape them: `50%` → `50\%` →
`50\textbackslash{}%`, which typesets the escape instead of the percent. The
module encodes that ordering in its replacement table and applies it as a
single compiled-alternation `re.sub` pass, so no substitution's output is ever
rescanned.

`escape_tex(None)` is `""` and non-strings are stringified, so a template can
interpolate a number or an absent field without a guard. The result is inert
text whatever the input was.

## Rendering (`app/latex/render.py`)

Jinja2 with **LaTeX-safe delimiters**, because `{{ … }}` is TeX grouping and
default-delimiter templates would be unreadable and ambiguous:

| Jinja construct | Default | Here |
| --------------- | ------- | ---- |
| Variable | `{{ … }}` | `<< … >>` |
| Block/statement | `{% … %}` | `<% … %>` |
| Comment | `{# … #}` | `<# … #>` |

`autoescape` is **off** — Jinja's autoescape is HTML escaping, which would
emit `&amp;` into a `.tex` file. Consequently the `tex` filter is **mandatory
at every interpolation site**:

```jinja
\section{<< section.heading | tex >>}
```

Applying it per site rather than globally keeps the few deliberately
unescaped values (macro names, hrefs already built by the renderer) visible as
exceptions instead of hiding them behind a default. The environment also sets
`StrictUndefined`, so a typo'd field is a render error rather than a silently
empty PDF, and registers two helper filters: `contact_url` (an explicit
`contact.url` wins; otherwise `mailto:`/`tel:`/`https://` is derived from the
kind) and `contact_icon` (contact kind → `fontawesome5` macro; unmapped kinds
render text-only).

`render_document_tex(document, template_id="tex-classic", settings=None)` is
the whole API. `settings` is an optional dict of template knobs; each template
reads only the keys it supports and ignores the rest. **No endpoint passes one
today** — both the `/tex*` routes and the diff's `mode: "tex"` render with
defaults — so the values below are what a generated `.tex` actually uses.

**Sections with nothing to show emit no heading.** `_renderable_sections`
drops invisible sections and sections that are empty *for their kind* — blank
`text`, no `entries`, all-blank `tags`, all-blank `groups` values — so an
empty section never leaves a dangling `\section{…}` rule in the PDF.

## The two templates

```
apps/backend/app/latex/templates/
├── _document.tex.j2   # shared body: header, sections, entries, bullets
├── classic.tex.j2     # tex-classic — preamble + include
└── compact.tex.j2     # tex-compact — preamble + include
```

Both preambles are modelled on a real-world `article` 10pt CV:
`tabularx`-based header, `titlesec` section styling, `fontawesome5` icons,
`enumitem` `\textbullet` lists, `hyperref` links. `tex-classic` uses
`geometry`'s `scale` with a `\titlerule` under each heading; `tex-compact`
uses fixed margins, unruled small-caps headings and tighter `parskip`/item
spacing for a history that has to fit on one page. Each reads a small number
of `settings` keys, each with a default it falls back to: `fontSize`
(`10`, the `article` class option in pt), plus `texScale` (`0.9`, classic) or
`texMargin` (`1.2cm`, compact).

Entry rendering in `_document.tex.j2`:

| Entry content | Renders as |
| ------------- | ---------- |
| bullets, no `summary` | `joblong` — title/period row, then the bullet `itemize` the environment opens |
| `summary` + bullets | `jobshort` with the summary paragraph, followed by a standalone `itemize` of the bullets |
| neither, or `summary` only | `jobshort` — title/period row plus the optional summary |

A bullet with `style: "plain"` renders `\item[]` (marker suppressed, matching
the HTML renderer's rule from
[resume-templates.md](resume-templates.md#bullet-styles-bulletstyle)); a
`bullet` style renders a normal `\item`. `entry.links` become icon-only
`\href`s on the title row. `tags` sections render as a `$|$`-separated line;
`groups` sections render as a two-column `tabularx` of `label: values`.

Publications and similar are ordinary `entries` sections, so **no biblatex**
is involved — Tectonic's bundled biblatex must version-match an external
biber, and a mismatch is a hard compile failure.

## Compiling (`app/latex/compile.py`)

### Engine detection

`latex_engine()` returns the absolute path of the preferred available engine,
or `None`:

1. `RESUME_MATCHER_LATEX_ENGINE` — if set, it is the only candidate. A bare
   name is resolved on `PATH`; an absolute path is accepted if it is a file.
   Nothing is inherited if the override does not resolve.
2. Otherwise the first hit of `tectonic` → `latexmk` → `xelatex` → `pdflatex`.

Tectonic is preferred because it downloads exactly the packages a document
needs instead of requiring a multi-GB distribution. `tectonic` and `latexmk`
loop internally and are run **once**; a bare `xelatex`/`pdflatex` is run
**twice**, so `tabularx` column widths and page references settle.

### The sandbox

| Control | Value | Why |
| ------- | ----- | --- |
| Working directory | a fresh `tempfile.TemporaryDirectory`, removed afterwards | the compile cannot see or leave artifacts in the app directory |
| `-no-shell-escape` | on every non-Tectonic invocation | no `\write18` shell-outs |
| `openin_any` / `openout_any` | `p` | TeX file reads/writes are confined to the working directory even if a template emitted an `\input` or `\openout` |
| Timeout | 120 s per engine run, then `kill()` | a runaway `\loop` or unclosed environment would otherwise burn CPU forever |
| `SOURCE_DATE_EPOCH` | `0` | reproducible PDF bytes |

**HOME and the engine caches are deliberately *not* redirected.** Tectonic
keeps its downloaded TeX bundle (hundreds of MB) under the user cache; a
per-run HOME would make every single compile re-fetch it. The temp cwd,
`-no-shell-escape` and the `openin_any`/`openout_any` restriction are the
sandbox.

### Failure surfaces

* No engine → `LatexUnavailableError`, which the router turns into **503**.
* Engine ran and produced no (or an empty) PDF → `LatexCompileError` carrying
  an excerpt of `resume.log`, which the router turns into **422**.
* `_error_excerpt` returns from the first line starting with `!` (TeX's error
  marker) for up to 40 lines / 4000 chars, and only falls back to the log tail.
  A raw tail would bury the one useful line under memory statistics.

## Endpoints

All under the `/api/v1` prefix; router `app/routers/tex.py`, schemas
`app/schemas/tex.py`.

| Method | Path | Query / body | Returns |
| ------ | ---- | ------------ | ------- |
| `GET` | `/resumes/tex/capabilities` | — | `{ engine, can_compile, templates }` — `engine` is the bare binary name or `null` |
| `GET` | `/resumes/{id}/tex` | `template` (default `tex-classic`), `regenerate` (default `false`) | `{ resume_id, source, is_override, template, engine }` |
| `PUT` | `/resumes/{id}/tex` | body `{ source }`, 1–400,000 chars | the same shape with `is_override: true`, `template: "custom"` |
| `DELETE` | `/resumes/{id}/tex` | `template` | the regenerated source with `is_override: false` |
| `GET` | `/resumes/{id}/tex/source` | `template` | the `.tex` as `application/x-tex`, `Content-Disposition: attachment` |
| `GET` | `/resumes/{id}/tex/pdf` | `template` | `application/pdf`, `Content-Disposition: attachment` |

`regenerate=true` ignores a saved override for that one read — a preview of
what resetting would give you, without touching stored state.

Download filenames come from the resume title with non-alphanumerics stripped
and spaces underscored, falling back to `resume.tex` / `resume.pdf`.

### Status codes

| Code | When |
| ---- | ---- |
| `400` | unknown `template` on a path that renders (`GET /tex`, `DELETE /tex`, the two downloads); the detail lists the valid ids |
| `404` | unknown resume id |
| `422` | **`/tex/pdf` only** — the engine ran and rejected the source. Detail is `{ message, log }`; the log is the user's own source failing, so it is theirs to read. Also the ordinary body-validation code for a `PUT` outside the 1–400,000-char range |
| `500` | the version/override write failed |
| `503` | **`/tex/pdf`** with no engine installed — the request is fine, the *capability* is missing, which is why it is not a `500`. The UI reads 503 as "offer the `.tex` download". Also returned for database write contention |

## Override lifecycle

```
GET  /resumes/{id}/tex        → generated from the document (is_override=false)
PUT  /resumes/{id}/tex        → override saved; version checkpoint origin="tex_edit",
                                tex_source_mode="edited"
     (document edits)         → override carried forward untouched
POST /resumes/{id}/restore    → that version's document AND its tex_source come back
DELETE /resumes/{id}/tex      → override cleared; checkpoint origin="tex_edit",
                                tex_source_mode="generated"
```

* **A `PUT` lands on the version timeline.** The document is unchanged by a
  source edit, so without recording the source, history would show that
  nothing happened and the edit could not be recovered. `tex_source`
  participates in version dedup for the same reason: a tex-only change whose
  document hash matches the head still creates a checkpoint.
* **Carry-forward.** `commit_resume_version` inherits the resume's current
  `tex_source` unless a caller passes one, so an ordinary document save keeps
  the override rather than silently dropping it from history.
* **Restore returns the pair.** A restore writes the past version's
  `tex_source` and `tex_source_mode` forward alongside its document —
  inheriting the *current* override would hand back a document/source
  combination that never existed.
* **Reset is not destructive.** `DELETE` writes a new `generated` checkpoint;
  the edited source is still on the timeline and can be restored.

Version rows therefore carry `tex_source_mode: "generated" | "edited"` and may
carry `origin: "tex_edit"`. See the version-history contract in
[front-end-apis.md](../apis/front-end-apis.md).

## Builder UI

A **LaTeX** tab in `apps/frontend/components/builder/resume-builder.tsx`
renders `apps/frontend/components/latex/latex-panel.tsx` beside the ordinary
paginated preview. The tab is disabled until the resume has been saved, since
generation reads the stored document.

| Panel behaviour | Detail |
| --------------- | ------ |
| State badge | `Generated` / `Edited`, from `is_override` |
| Template buttons | `Classic` / `Compact`; **disabled while an override is active**, because the override is not a template render |
| Override notice | Explains that document changes no longer update this source until reset |
| No-engine notice | Shown when `capabilities.can_compile` is false; the Download PDF button is disabled with the same message as its tooltip |
| Save | `PUT`, enabled only when the textarea differs from the server copy |
| Reset to generated | `DELETE`, behind a confirm dialog that says the edited version stays on the timeline |
| Download `.tex` | Always available — the one export that cannot fail |
| Download PDF | Compiles; on 422 the engine log is rendered in a scrollable `<pre>` under the error |
| Refresh | The parent bumps a `revision` prop after a document save so a *generated* source refetches |

Strings live under the `latex.*` i18n block in every locale
(`apps/frontend/messages/*.json`) — see [i18n.md](i18n.md).

## Deployment

The engine is optional everywhere. With none installed, generation, editing,
reset and `.tex` download all work; only in-container compilation is
unavailable.

| Knob | Kind | Default | Effect |
| ---- | ---- | ------- | ------ |
| `INSTALL_LATEX` | Docker build arg | `true` | Downloads a static Tectonic binary (~30 MB) and warms its TeX bundle at build time. `false` gives a smaller image with no engine: `/tex/pdf` answers 503 and the UI offers the `.tex` |
| `RESUME_MATCHER_LATEX_ENGINE` | Runtime env var | unset | Pins the engine (name on `PATH` or absolute path) instead of auto-detecting `tectonic` → `latexmk` → `xelatex` → `pdflatex` |

```bash
# Smaller image, no in-container compilation
INSTALL_LATEX=false docker compose build

# Pin an engine at runtime
RESUME_MATCHER_LATEX_ENGINE=xelatex docker compose up -d
```

Tectonic is only fetched for `amd64`/`arm64`; other architectures build
without an engine. Running outside Docker, install Tectonic (or any TeX
distribution) on the machine running the backend — the backend detects it on
`PATH` at request time, so no restart-time configuration is involved beyond
the override. Full deployment reference: [SETUP.md](../../../SETUP.md).

## Key files

| File | Purpose |
| ---- | ------- |
| `apps/backend/app/latex/escape.py` | `escape_tex` — the escaping boundary |
| `apps/backend/app/latex/render.py` | Jinja environment, `LATEX_TEMPLATES`, `render_document_tex` |
| `apps/backend/app/latex/compile.py` | `latex_engine`, `compile_tex_to_pdf`, the sandbox, error excerpting |
| `apps/backend/app/latex/templates/` | `_document.tex.j2` plus `classic`/`compact` preambles |
| `apps/backend/app/routers/tex.py` | The `/resumes/**/tex*` routes — five paths, six operations |
| `apps/backend/app/schemas/tex.py` | `TexCapabilities`, `TexSourceResponse`, `TexSourceUpdate` |
| `apps/backend/migrations/versions/` | `0004_tex_source` — `resumes.tex_source` |
| `apps/frontend/lib/api/tex.ts` | Client, plus `TexCompileError` / `TexUnavailableError` |
| `apps/frontend/components/latex/latex-panel.tsx` | The editor and export panel |
| `Dockerfile`, `docker-compose.yml` | `INSTALL_LATEX`, bundle warm-up, `RESUME_MATCHER_LATEX_ENGINE` |

Dependency: `jinja2==3.1.6` (`apps/backend/pyproject.toml`).
