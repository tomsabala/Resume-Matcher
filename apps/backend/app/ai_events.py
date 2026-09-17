"""Recent AI failures, so the dashboard can show why an operation failed.

Before this, a model that answered with truncated or malformed JSON left
nothing behind but a server log line: the UI showed a generic "please try
again" and the user had no way to tell an output-budget problem from a bad API
key. These records are what the dashboard's diagnostics panel reads.

Deliberately **in-process and bounded**: this is a diagnostic tail, not an
audit log. It does not survive a restart and it must never grow unbounded, so
a failing provider cannot fill memory with error text.

Records are **scoped**: each one carries the workspace that was active when it
was made, and the diagnostics endpoints serve only their caller's own. Without
that filter one tenant would read another's provider error text, which can
quote fragments of that tenant's prompt. The bound, though, stays global —
``maxlen`` counts every workspace's records together, so a busy tenant can
evict another tenant's history. That is acceptable for a best-effort
diagnostics tail, and not worth a deque per workspace.

**No model output, prompt, resume or job text is ever recorded** — only the
shape of the failure: which operation, which category, which model, and the
budget it ran into. Everything stored here is safe to show a client.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from app.tenancy import current_workspace_id

logger = logging.getLogger(__name__)

__all__ = [
    "AIFailure",
    "AIFailureKind",
    "MAX_TRACKED_AI_FAILURES",
    "clear_ai_failures",
    "record_ai_failure",
    "recent_ai_failures",
]

# One screenful of history. Older entries are the least useful: the user is
# looking at what just went wrong.
MAX_TRACKED_AI_FAILURES = 20

# Cap on the operator-facing message. Provider errors can be kilobytes of
# JSON, and this value is rendered in a UI panel.
MAX_FAILURE_DETAIL_CHARS = 300

AIFailureKind = Literal["truncated", "malformed", "empty", "invalid", "provider"]


@dataclass(frozen=True)
class AIFailure:
    """One failed AI operation, in terms safe to show a client."""

    id: str
    at: str  # ISO-8601 UTC
    workspace_id: str  # the scope the failure happened in; never sent to a client
    operation: str  # the schema the call was producing: resume, diff, …
    kind: AIFailureKind
    detail: str
    model: str | None = None
    provider: str | None = None
    attempts: int | None = None
    max_tokens: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """The client-facing fields.

        ``workspace_id`` is how the tail is filtered, not something a client is
        told about — the response model has no such field.
        """
        fields = asdict(self)
        fields.pop("workspace_id")
        return fields


_failures: deque[AIFailure] = deque(maxlen=MAX_TRACKED_AI_FAILURES)
_lock = threading.Lock()


def classify_ai_failure(error: BaseException) -> AIFailureKind:
    """Map an exception to the category the dashboard explains to the user.

    Imported lazily to keep this module free of an ``app.llm`` import cycle:
    ``app.llm`` records failures, so it cannot be imported at module scope.
    """
    from json import JSONDecodeError

    from app.llm import TruncatedCompletionError

    if isinstance(error, TruncatedCompletionError):
        return "truncated"
    if isinstance(error, JSONDecodeError):
        return "malformed"
    message = str(error).lower()
    if "empty response" in message:
        return "empty"
    if isinstance(error, ValueError):
        # A schema/source validator rejected an otherwise parseable answer.
        return "invalid"
    return "provider"


def record_ai_failure(
    *,
    operation: str,
    kind: AIFailureKind,
    detail: str,
    model: str | None = None,
    provider: str | None = None,
    attempts: int | None = None,
    max_tokens: int | None = None,
) -> AIFailure:
    """Append one failure to the tail and return it.

    A caller with no request tenant — a background task, a startup migration,
    a script — records against ``""``, which no endpoint can ask for.
    """
    failure = AIFailure(
        id=str(uuid4()),
        at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        workspace_id=current_workspace_id() or "",
        operation=operation,
        kind=kind,
        detail=detail.strip()[:MAX_FAILURE_DETAIL_CHARS],
        model=model,
        provider=provider,
        attempts=attempts,
        max_tokens=max_tokens,
    )
    with _lock:
        _failures.append(failure)
    return failure


def recent_ai_failures(workspace_id: str) -> list[AIFailure]:
    """One workspace's tracked failures, newest first."""
    with _lock:
        return [
            failure
            for failure in reversed(_failures)
            if failure.workspace_id == workspace_id
        ]


def clear_ai_failures(workspace_id: str) -> int:
    """Drop one workspace's failures and return how many were dismissed.

    Other workspaces' entries stay: one user emptying their panel must not
    blind another.
    """
    with _lock:
        kept = [
            failure for failure in _failures if failure.workspace_id != workspace_id
        ]
        dismissed = len(_failures) - len(kept)
        _failures.clear()
        _failures.extend(kept)
    return dismissed
