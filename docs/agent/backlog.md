# Backlog

Known work that is deliberately deferred. Issues are disabled on this repository,
so this file is the tracker. One heading per item; delete the item when it lands.

---

## Wall-clock budgets in the backend tests are runner-sensitive

**Status:** open · **Raised:** 2026-09-22 · **Area:** `apps/backend/tests/integration/`

Moving the suite to CI surfaced two tests that assert on ordering but encode it
as a wall-clock margin small enough for a shared runner to reorder. Both passed
1543/1543 locally and went red on the runner; both were widened rather than
skipped, because the ordering they check is real:

- `test_ai_operation_budgets.py::test_deadline_during_claim_retires_committed_owner_before_returning`
  — paired a 0.04 s request budget with a 0.1 s sleep, so the deadline had a
  60 ms window to land in.
- `test_confirmation_transactions.py::test_optional_title_timeout_can_still_commit_required_resume`
  — a 1 s budget, of which the endpoint gives optional work 80 %, left the commit
  transaction 200 ms.

Widening the margins is a patch, not a fix: the tests still depend on the machine
being fast enough. The durable version injects a clock or drives the deadline
from an event the test controls, so ordering is asserted instead of raced. Worth
doing the next time one of these goes red rather than pre-emptively — there may
be no third.
