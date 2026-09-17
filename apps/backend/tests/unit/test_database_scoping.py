"""Structural tripwire: every tenant-owned query in the facade is scoped.

``app/database.py`` is the only layer that can reach a document row, so it is
the only place a cross-tenant read can be introduced. These two rules make that
mechanical rather than a matter of review attention:

* **Rule A** — no ``session.get(Model, …)`` on a tenant-owned model. A primary
  key lookup carries no workspace predicate, so it always crosses tenants.
* **Rule B** — every ``select``/``update``/``delete`` naming a tenant-owned
  model mentions ``workspace_id`` somewhere in the same statement.

Deliberately syntactic, with no allowlist. A few of the predicates it forces
are redundant (a version id read from an already-scoped resume, say), and that
redundancy is the price of a rule that cannot be argued with — and that fails
loudly the next time an upstream merge reintroduces an unscoped load.

``Workspace`` is exempt: it *is* the tenant table, the one place ``tenant_ref``
is read. ``WorkspaceSetting`` is exempt because ``workspace_id`` is part of its
primary key, so no lookup of it can be unscoped.
"""

from __future__ import annotations

import ast
from pathlib import Path

DATABASE_PATH = Path(__file__).resolve().parents[2] / "app" / "database.py"

TENANT_OWNED_MODELS = frozenset(
    {
        "Resume",
        "ResumeVersion",
        "Job",
        "Application",
        "TailoringPreview",
        "Improvement",
        "ApiKey",
    }
)

STATEMENT_BUILDERS = frozenset({"select", "update", "delete"})


def _module() -> ast.Module:
    return ast.parse(DATABASE_PATH.read_text(encoding="utf-8"))


def _called_name(node: ast.Call) -> str | None:
    """``select`` for ``select(...)``, ``get`` for ``session.get(...)``."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _first_arg_model(node: ast.Call) -> str | None:
    """The model named by the statement's first argument, if any.

    Handles ``select(Resume)``, ``select(Resume.resume_id)`` and
    ``select(func.count()).select_from(Resume)``'s inner call alike, because
    every form starts from a ``Name`` or an ``Attribute`` on one.
    """
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Name):
        return first.id
    if isinstance(first, ast.Attribute) and isinstance(first.value, ast.Name):
        return first.value.id
    return None


def _mentions_workspace_id(node: ast.AST) -> bool:
    """True when the expression touches ``workspace_id`` anywhere inside it."""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr == "workspace_id":
            return True
        # `.where(**{...})` / keyword form, and `model.workspace_id` reached
        # through a loop variable both land here.
        if isinstance(child, ast.keyword) and child.arg == "workspace_id":
            return True
        if isinstance(child, ast.Constant) and child.value == "workspace_id":
            return True
    return False


def _statement_expressions(tree: ast.Module) -> list[ast.expr]:
    """Outermost expressions, so a chained ``select(...).where(...)`` is one unit.

    Rule B has to see the whole chain: the model is named by the innermost
    call and the predicate by an outer ``.where``.
    """
    outermost: list[ast.expr] = []
    for node in ast.walk(tree):
        for field, value in ast.iter_fields(node):
            items = value if isinstance(value, list) else [value]
            for item in items:
                if isinstance(item, (ast.Call, ast.Await)) and not isinstance(
                    node, (ast.Call, ast.Await, ast.Attribute)
                ):
                    outermost.append(item)
    return outermost


def test_no_primary_key_get_on_a_tenant_owned_model() -> None:
    """Rule A: a ``session.get`` on a document row cannot be workspace-scoped."""
    offenders = [
        f"{DATABASE_PATH.name}:{node.lineno} session.get({model}, …)"
        for node in ast.walk(_module())
        if isinstance(node, ast.Call)
        and _called_name(node) == "get"
        and (model := _first_arg_model(node)) in TENANT_OWNED_MODELS
    ]
    assert not offenders, "Unscoped primary-key loads:\n" + "\n".join(offenders)


def test_every_tenant_owned_statement_carries_a_workspace_predicate() -> None:
    """Rule B: a statement naming a document table mentions ``workspace_id``."""
    tree = _module()
    offenders: list[str] = []
    for expression in _statement_expressions(tree):
        if _mentions_workspace_id(expression):
            continue
        for node in ast.walk(expression):
            if not isinstance(node, ast.Call):
                continue
            if _called_name(node) not in STATEMENT_BUILDERS:
                continue
            model = _first_arg_model(node)
            if model in TENANT_OWNED_MODELS:
                offenders.append(
                    f"{DATABASE_PATH.name}:{node.lineno}"
                    f" {_called_name(node)}({model}) has no workspace_id predicate"
                )
    assert not offenders, "Unscoped statements:\n" + "\n".join(sorted(set(offenders)))


def test_the_tripwire_would_notice_a_regression() -> None:
    """The rules above are only worth having if they actually fire.

    Without this, a refactor that broke the AST walk would leave two tests
    that pass against anything.
    """
    regression = ast.parse(
        "async def leak(session, resume_id):\n"
        "    a = await session.get(Resume, resume_id)\n"
        "    b = await session.execute(select(Resume).where("
        "Resume.resume_id == resume_id))\n"
        "    return a, b\n"
    )

    gets = [
        node
        for node in ast.walk(regression)
        if isinstance(node, ast.Call)
        and _called_name(node) == "get"
        and _first_arg_model(node) in TENANT_OWNED_MODELS
    ]
    assert len(gets) == 1

    unscoped = [
        node
        for expression in _statement_expressions(regression)
        if not _mentions_workspace_id(expression)
        for node in ast.walk(expression)
        if isinstance(node, ast.Call)
        and _called_name(node) in STATEMENT_BUILDERS
        and _first_arg_model(node) in TENANT_OWNED_MODELS
    ]
    assert len(unscoped) == 1
