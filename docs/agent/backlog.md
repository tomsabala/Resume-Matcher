# Backlog

Known work that is deliberately deferred. Issues are disabled on this repository,
so this file is the tracker. One heading per item; delete the item when it lands.

---

## ~~Move the test suites off the pre-push hook and into CI~~ — done

**Status:** done 2026-09-22 · **Area:** `.githooks/`, `.github/workflows/`

Kept for the reasoning, not as open work. `.github/workflows/tests.yml` now runs
both suites plus eslint on pushes to `main`/`dev` — and deliberately **not** on
`pull_request`, so external contributor PRs still trigger nothing. The pre-push
hook keeps only locale parity and `tsc --noEmit`: **3 seconds**, down from 12–15
minutes. The release image build moved to `v*.*.*` tags in the same pass, so a
commit no longer costs ~17 minutes of QEMU-emulated arm64 either.

What is left, if it ever hurts again: `pytest-xdist` is not a dependency and a
large part of the backend suite writes to SQLite, so parallelising it needs
per-worker database isolation and a pass-count comparison first.

### Problem

`git push` took 12–15 minutes. Almost all of it was one step:

| step | time |
| --- | --- |
| `uv run pytest` (1543 backend tests) | ~9–14 min |
| locale parity | instant |
| `vitest run` (548 frontend tests) | ~30 s |
| `tsc --noEmit` | ~15 s |
| the actual git transfer | ~3 s |

`.githooks/README.md` still describes the backend suite as "~8s". That was true
when the gate was written; the suite has since grown to 1543 tests and is now the
entire cost of pushing. A developer pays it on every push, serially, on their own
machine, blocking their terminal — and pays it again for a one-line fixup.

Two failures already traced back to running it here rather than on a runner:

- The gate inherits the caller's environment. A shell with ROS sourced exports a
  `PYTHONPATH` of foreign site-packages; pytest autoloads their `pytest11` entry
  points, `launch_testing` imports `lark`, and collection dies before a single
  test runs. Worked around in `5d44caa` by dropping `PYTHONPATH` for that command.
- The gate runs the frontend suite immediately after the backend suite, on a
  loaded machine, so heavy specs hit vitest's 5 s wall-clock default and timed out
  on trees that pass 11/11 standalone. Worked around in `1dc66c7` by raising
  `testTimeout`. Both are symptoms of "a runner's job, run on a laptop".

### Why it is this way

Deliberate, and the reasoning is still sound as far as it goes: the repo takes a
high volume of external contributor PRs and a PR-triggered workflow would run on
every one of them. See `.githooks/README.md`.

### Options

1. **Push-triggered CI on `main` only.** A workflow on `push` to `main`/`dev`
   (not `pull_request`) costs nothing on contributor PRs and is exactly the set
   the hook protects today. The hook then drops to the fast checks — locale
   parity and `tsc`, ~15 s — or goes away.
2. **`pull_request` CI limited to collaborators.** `if: github.event.pull_request.head.repo.full_name == github.repository`
   skips fork PRs entirely, which is the volume the hook exists to avoid.
3. **Keep the hook, parallelise it.** `pytest -n auto` with `pytest-xdist` should
   take ~9 min to ~3 min on a 12-core box. Cheapest change, does not fix the
   "runs in the developer's environment" class of failure above. Requires
   confirming the suite is xdist-safe (compare pass counts both ways before
   committing to it).

`pytest-xdist` is **not** currently a dependency, and a large part of this suite
writes to SQLite, so option 3 is not a one-liner: it needs per-worker database
isolation and a pass-count comparison before it can be trusted.

### Already done

- The release image build (`docker-publish.yml`, ~17 min of QEMU-emulated arm64)
  no longer runs on every push to `main` — it runs on `v*.*.*` tags and on
  manual dispatch. The image that actually gets deployed is `apps-image.yml`
  (~3 min, amd64, still on push). That alone removed more wall-clock per commit
  than the whole frontend gate costs.

Options 1 and 3 compose. Prefer 1; 3 is a stopgap.

### Done when

- Pushing `main` does not run the full backend suite locally.
- `main` is still gated — a red suite is visible and attributable before anyone
  pulls it.
- Contributor PRs still trigger no test workflow.
- `.githooks/README.md` describes what the hook actually does, with honest timings.
