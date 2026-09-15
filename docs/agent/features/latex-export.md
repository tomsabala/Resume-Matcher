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
> with this feature. The id is still `latex` (saved settings pin it), but the
> UI calls it **Academic Serif**, because labelling a Chromium render "LaTeX"
> is how a browser-rendered PDF gets mistaken for engine output. The LaTeX
> export templates are the `tex-`prefixed ids and live in
> `apps/backend/app/latex/templates/`. In prose: **"the `latex` HTML
> template"** vs **"the LaTeX export"**.

Both targets are offered by the **same** template picker in the builder: each
`TEMPLATE_OPTIONS` row carries `target: 'html' | 'tex'`, and the selection
decides which endpoint the preview and the export use. See
[Builder UI](#builder-ui).

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
| `<` `>` `\|` | `\textless{}` `\textgreater{}` `\textbar{}` |

The last row is typography, not safety: those three are harmless to the
parser, but OT1 Computer Modern — the encoding the reference CV uses — maps
them to `¡`, `¿` and `—`, so a skills line reading `Java | Python` printed em
dashes.

A second table maps the unicode the engine cannot typeset at all (`≥ ≤ ≈ ≠ ↔
⇒ ⟶ ∞ √ ★ ✓ π α β λ ∙ ‣ ′ ″ « »` and U+2060) to math-mode or text macros;
each of those aborted the compile with *Unicode character … not set up for
use with LaTeX*. Characters that already typeset (`→ ← ± × ÷ • ° – — … “ ” €
£ § ¶ © ® ½ µ ·`) are deliberately absent. `«`/`»` become typographic double
quotes because no guillemet macro exists without `fontenc[T1]`, and switching
encoding would move every glyph away from the reference's Computer Modern.
Anything outside both tables (Hebrew, CJK, emoji) passes through and the
engine rejects it by name — the panel shows that log line, which beats
silently deleting content.

**Backslash is escaped first.** Every other replacement *introduces*
backslashes, so handling `\` last would re-escape them: `50%` → `50\%` →
`50\textbackslash{}%`, which typesets the escape instead of the percent. The
module encodes that ordering in its replacement table and applies both tables
as a single compiled-alternation `re.sub` pass, so no substitution's output is
ever rescanned — which matters doubly for the unicode macros, whose values are
themselves full of backslashes and `$`.

`escape_tex(None)` is `""` and non-strings are stringified, so a template can
interpolate a number or an absent field without a guard. The result is inert
text whatever the input was.

### Bullets are rich text (`escape_tex_rich`, filter `tex_rich`)

Bullets are the one field edited with TipTap and stored as sanitised HTML, so
`escape_tex` printed their markup: `<strong>x</strong>` typeset as
`¡strong¿x¡/strong¿`. `escape_tex_rich` converts the tag set the frontend
sanitiser allows and escapes everything else:

| Markup | LaTeX |
| ------ | ----- |
| `<strong>` `<b>` | `\textbf{…}` |
| `<em>` `<i>` | `\textit{…}` |
| `<u>` | `\underline{…}` |
| `<a href>` | `\href{…}{…}` for `http`/`https`/`mailto`/`tel`/`www.` only; any other scheme keeps the text and drops the link |
| `<br>` | `\\` |
| `</p><p>` | `\par` |
| anything else | dropped, inner text kept |

Entities are decoded before escaping (`&amp;` → `&` → `\&`), and the output is
always brace-balanced: an unclosed tag is closed at the end and a stray close
tag ignored, because an unbalanced group is a failed compile. Only bullets use
this filter — every other field is plain text and keeps `| tex`.

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
empty PDF, and registers the helper filters below.

| Filter | Purpose |
| ------ | ------- |
| `tex` | `escape_tex` — mandatory on every plain-text interpolation |
| `tex_rich` | `escape_tex_rich` — bullets only |
| `dates` | `2023 - May 2026` → `2023 -- May 2026`; spaces required on both sides, so `Full-stack` is untouched. Render-time typography: the stored `period` stays verbatim |
| `contact_url` | An explicit `contact.url` wins; otherwise `mailto:`/`tel:`/`https://` is derived from the kind |
| `contact_icon` | Contact kind → `fontawesome5` macro; unmapped kinds render text-only |
| `renderable_contacts` | A contact renders when it has *any* of label, value or url — matching the HTML header, where an empty label plus an icon means an icon-only link |

`render_document_tex(document, template_id="tex-classic", settings=None)` is
the whole API. `settings` is an optional dict of template knobs; each template
reads only the keys it supports and ignores the rest. The `/tex*` routes pass
exactly one: `{"pageSize": pageSize}` from their `pageSize` query parameter
(`A4` | `LETTER`), which selects `a4paper` or `letterpaper` in both preambles.
The diff's `mode: "tex"` still renders with defaults, so every other value
below is what a generated `.tex` actually uses.

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
`bullet` style renders a normal `\item`, and bullet text goes through
`tex_rich` rather than `tex`. `entry.links` render as `\href`ed icons in the
row's **right-hand cell**, after the period — flush with the margin, the way
the reference CV places a repo link beside a project name. `tags` sections
render as a `$|$`-separated line; `groups` sections render as a two-column
`tabularx` of `label: values`.

### Vertical rhythm is three named macros

Each preamble defines `\resumeEntryGap` (between entries), `\resumeSectionEnd`
(after an entries section) and `\resumeBlockEnd` (after text/tags/groups), and
`_document.tex.j2` uses only those names. The section trailer is the length
that decides whether a resume fits one page: a uniform `\vspace{-6pt}` left a
~19pt hole and pushed the last section onto page 2, against 13.8–15.4pt in the
reference CV. Classic uses `-11pt`, compact `-9pt` — compact sets
`\parskip` to 2pt, so the same `\vspace` yields a larger gap, and it must stay
the denser of the two. The values are tuned to those `\parskip` settings; if a
template changes `\parskip`, re-measure with the gap assertion in
`tests/unit/test_latex_compile.py` rather than copying the number.

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
| `GET` | `/resumes/{id}/tex` | `template` (default `tex-classic`), `pageSize` (default `A4`), `regenerate` (default `false`) | `{ resume_id, source, is_override, template, engine }` |
| `PUT` | `/resumes/{id}/tex` | body `{ source }`, 1–400,000 chars | the same shape with `is_override: true`, `template: "custom"` |
| `DELETE` | `/resumes/{id}/tex` | `template`, `pageSize` | the regenerated source with `is_override: false` |
| `GET` | `/resumes/{id}/tex/source` | `template`, `pageSize` | the `.tex` as `application/x-tex`, `Content-Disposition: attachment` |
| `GET` | `/resumes/{id}/tex/pdf` | `template`, `pageSize` | `application/pdf`, `Content-Disposition: attachment` |

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

**One picker chooses the renderer.** Template & Formatting lists all nine
templates (`TEMPLATE_OPTIONS`), each carrying `target: 'html' | 'tex'`, and
`isTexTemplate(settings.template)` is the single predicate every call site
reads. Selecting **LaTeX Classic** or **LaTeX Compact** switches the RESUME
pane to the engine-compiled PDF and routes the header's Download PDF through
`compileTexPdf`; `getResumePdfUrl` throws for a tex template rather than
emitting a `/pdf` URL, and `GET /resumes/{id}/pdf` answers **400** for one.
Before this, the picker and the LaTeX tab held two separate choices and
Download PDF always used Chromium.

Page size is the only formatting control a tex selection keeps; the margin,
spacing, font-size, font-family, compact-mode, contact-icon and accent-colour
controls are disabled with a notice, because the engine reads none of them.
The two tex options render `disabled` when `getTexCapabilities()` reports no
engine — selecting one there would 503 on every preview and download.

The **LaTeX** tab (`apps/frontend/components/builder/resume-builder.tsx`)
renders `apps/frontend/components/latex/latex-panel.tsx` beside
`apps/frontend/components/latex/tex-pdf-preview.tsx` — the *engine-compiled*
PDF, not the browser-rendered HTML template. Those are two different
renderers with different fonts and metrics, so previewing the HTML one here
showed something the tab's own Download PDF could never produce. The tab
follows `templateSettings.template`, falling back to `tex-classic` (with a
notice offering to switch) when an HTML template is selected, and a
`texRevision` counter keeps the panel and the preview compiling the same
thing. The tab is disabled until the resume has been saved, since generation
reads the stored document.

| Panel behaviour | Detail |
| --------------- | ------ |
| State badge | `Generated` / `Edited`, from `is_override` |
| Template chip | The selected tex template, read-only — the picker owns the choice |
| HTML-selection notice | Shown when the picker holds an HTML template; a button switches to `tex-classic` |
| Override notice | Explains that document changes no longer update this source until reset |
| No-engine notice | Shown when `capabilities.can_compile` is false; the Download PDF button is disabled with the same message as its tooltip |
| Save | `PUT`, enabled only when the textarea differs from the server copy |
| Reset to generated | `DELETE`, behind a confirm dialog that says the edited version stays on the timeline |
| Download `.tex` | Always available — the one export that cannot fail |
| Download PDF | Compiles; on 422 the engine log is rendered in a scrollable `<pre>` under the error |
| Refresh | The parent bumps a `revision` prop after a document save so a *generated* source refetches |
| Compiled preview | `compileTexPdf` on mount and on every template/page-size/revision change, shown in an `<object>`; object URLs are revoked on cleanup. A missing engine, a compile failure (with its log) and any other error each render in place |

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
| `apps/backend/app/latex/escape.py` | `escape_tex` (the escaping boundary) and `escape_tex_rich` (bullet HTML → LaTeX) |
| `apps/backend/app/latex/render.py` | Jinja environment, `LATEX_TEMPLATES`, `render_document_tex` |
| `apps/backend/app/latex/compile.py` | `latex_engine`, `compile_tex_to_pdf`, the sandbox, error excerpting |
| `apps/backend/app/latex/templates/` | `_document.tex.j2` plus `classic`/`compact` preambles |
| `apps/backend/app/routers/tex.py` | The `/resumes/**/tex*` routes — five paths, six operations |
| `apps/backend/app/schemas/tex.py` | `TexCapabilities`, `TexSourceResponse`, `TexSourceUpdate` |
| `apps/backend/migrations/versions/` | `0004_tex_source` — `resumes.tex_source` |
| `apps/frontend/lib/api/tex.ts` | Client, plus `TexCompileError` / `TexUnavailableError` |
| `apps/frontend/lib/types/template-settings.ts` | `TEMPLATE_OPTIONS` with each template's `target`, and `isTexTemplate` |
| `apps/frontend/components/latex/latex-panel.tsx` | The editor and export panel |
| `apps/frontend/components/latex/tex-pdf-preview.tsx` | The compiled-PDF pane used by the RESUME, HISTORY and LaTeX panes |
| `Dockerfile`, `docker-compose.yml` | `INSTALL_LATEX`, bundle warm-up, `RESUME_MATCHER_LATEX_ENGINE` |

Dependency: `jinja2==3.1.6` (`apps/backend/pyproject.toml`).
