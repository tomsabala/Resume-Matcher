# Local git hooks (`.githooks/`)

Version-controlled git hooks for Resume-Matcher.

We **do not** run a `pull_request`-triggered workflow: the repo gets a high
volume of external contributor PRs and CI would run on every one of them. What
we do run is [`tests.yml`](../.github/workflows/tests.yml), triggered on pushes
to `main`/`dev` only — the same set the pre-push hook used to protect, without
costing a developer their terminal.

## What runs where

| Check | Where | Cost |
| --- | --- | --- |
| Locale parity | `pre-push` **and** CI | instant |
| `tsc --noEmit` | `pre-push` **and** CI | ~15 s |
| Backend suite (1543 tests) | CI only | ~9–14 min, on a runner |
| Frontend suite (548 tests) | CI only | ~30 s, on a runner |
| `eslint` | CI only | ~18 s, on a runner |

`pre-push` blocks the push if either of its two checks is red. It takes about
**3 seconds**. It previously ran both test suites, which made a push cost 12–15
minutes of local, serial, terminal-blocking wall time — paid again for every
one-line fixup. The two checks that stayed are the ones fast enough to be free.

Both always run, so you see **all** failures at once.

## Activate (once per clone)

```bash
git config core.hooksPath .githooks
```

That's it — hooks are now active for this clone. (It's a local git setting; it
does not affect anyone else who clones the repo, by design.)

## Everyday use

- Commit freely — the gate runs at **push**, not on every commit.
- If the gate fails, the push is aborted and the failures are printed. Fix them and push again.
- A push is not the last word any more: the suites run on the runner afterwards.
  Watch them with `gh run watch`, or `gh run list --workflow=tests.yml`.

## Escape hatches

```bash
git push --no-verify          # bypass the gate once (docs-only / WIP branches)
git config --unset core.hooksPath   # disable the hooks entirely
```

## Run the checks manually

```bash
cd apps/backend && env -u PYTHONPATH uv run pytest   # backend suite
python3 scripts/check_locale_parity.py               # locale parity (from repo root)
cd apps/frontend && npm run test                     # frontend suite (vitest)
```

`env -u PYTHONPATH` matters only if your shell has sourced something that exports
one — ROS (`/opt/ros/*/setup.bash`), conda, a
system Python. pytest autoloads every `pytest11` entry point it can see, so those
foreign site-packages get loaded into this venv's run; on a ROS box that pulls in
`launch_testing`, which imports `lark`, which is not installed here, and
collection dies before a single test runs. Plain `uv run pytest` is fine in a
clean shell.

See [`docs/agent/testing-strategy.md`](../docs/agent/testing-strategy.md) for the
full testing strategy this gate enforces.
