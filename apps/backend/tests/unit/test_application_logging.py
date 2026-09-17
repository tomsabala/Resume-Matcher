"""Application log records must actually reach a handler.

``_configure_application_logging`` set a level on the ``app`` logger and stopped
there. Uvicorn's ``dictConfig`` configures only its own ``uvicorn*`` loggers and
leaves the root logger bare, so every ``app.*`` record propagated to a
handler-less root and fell through to ``logging.lastResort``, which drops
anything below WARNING. The effect was that no ``logger.info`` in the
application was ever visible in ``docker logs`` — including the startup lines
that report the effective tenant mode and the data migrations, which exist
precisely so a mis-set ``TENANT_MODE`` is noticed before two visitors see each
other's resumes.

``caplog`` cannot catch this: pytest attaches its own handler to the root logger
and forces propagation, so a record is captured whether or not the application
would have emitted it. These tests check the handler chain instead.
"""

import logging

import app.main  # noqa: F401 - importing runs _configure_application_logging


def _has_reachable_handler(logger: logging.Logger) -> bool:
    """True when a record at the logger's level would reach some handler.

    Mirrors ``logging.Logger.callHandlers``: walk the logger and its ancestors
    while propagation allows it, and report whether any of them has a handler.
    """
    current: logging.Logger | None = logger
    while current is not None:
        if current.handlers:
            return True
        if not current.propagate:
            return False
        current = current.parent
    return False


def test_application_info_records_reach_a_handler() -> None:
    app_logger = logging.getLogger("app")
    assert app_logger.isEnabledFor(logging.INFO)
    assert _has_reachable_handler(app_logger), (
        "app.* records would be dropped by logging.lastResort — setting a level "
        "without a handler discards every logger.info in the application"
    )


def test_a_child_logger_reaches_it_too() -> None:
    """Every module logs through ``logging.getLogger(__name__)``, i.e. ``app.x``."""
    assert _has_reachable_handler(logging.getLogger("app.routers.resumes"))


def test_configuring_twice_does_not_stack_handlers() -> None:
    """The module runs it at import; a reload or a second call must not duplicate."""
    app_logger = logging.getLogger("app")
    before = len(app_logger.handlers)
    app.main._configure_application_logging()
    assert len(app_logger.handlers) == before
