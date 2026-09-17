"""Shared config file cache used by multiple routers.

This module owns the cached read of ``config.json`` so that routers
(resumes, enrichment, config) can share it without importing each other.

``config.json`` is the **instance default** layer. On top of it sits one
optional per-workspace override row per key (``workspace_settings``), so a
tenant can choose its own provider, model, language, feature toggles and
prompts without touching a file it does not own. The merged view is what every
caller sees, and both entry points — :func:`load_config` here and
``config.load_config_file`` — must produce the same one, or ``GET /config``
would disagree with what the LLM path actually uses.
"""

import copy
import json
import logging
import time
from pathlib import Path
from typing import Any

from app.config import get_config_path

logger = logging.getLogger(__name__)

# The keys a tenant may own. `config.json` is flat, so this is a flat
# allowlist: an override replaces the instance value for exactly that key.
# Everything else in the file (paths, anything an operator adds out of band)
# stays instance-wide and is deliberately not exposed per tenant.
OVERRIDABLE_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        # LLM routing
        "provider",
        "model",
        "api_base",
        "reasoning_effort",
        # Feature toggles
        "enable_cover_letter",
        "enable_outreach_message",
        "enable_interview_prep",
        # Language
        "ui_language",
        "content_language",
        "language",
        # Prompt selection and custom prompts
        "default_prompt_id",
        "cover_letter_prompt",
        "outreach_message_prompt",
    }
)

# Cache state — accessed without a lock because:
# 1. The app runs single-worker uvicorn (one thread, cooperative async).
# 2. The GIL protects dict/float assignment; worst-case TOCTOU is a
#    redundant disk read (benign, same file, same result).
# 3. A threading.Lock would block the event loop; an asyncio.Lock would
#    require making load_config async and changing every caller.
#
# Keyed by ``(path, workspace_id)``: the merged view differs per tenant, so a
# path-only key would serve one tenant's provider to another.
_config_cache: dict[tuple[Path, str], dict[str, Any]] = {}
_config_cache_time: dict[tuple[Path, str], float] = {}
_CONFIG_CACHE_TTL: float = 300.0  # 5 minutes


def invalidate_config_cache(workspace_id: str | None = None) -> None:
    """Invalidate the config cache so the next read fetches from disk.

    Call this after any write to ``config.json`` (no argument — every tenant's
    merged view changes) or to one workspace's overrides (pass its id).
    """
    if workspace_id is None:
        _config_cache.clear()
        _config_cache_time.clear()
        return
    for key in [k for k in _config_cache if k[1] == workspace_id]:
        _config_cache.pop(key, None)
        _config_cache_time.pop(key, None)


def merge_workspace_overrides(
    instance_config: dict[str, Any], overrides: dict[str, Any]
) -> dict[str, Any]:
    """Instance config with this workspace's overridable keys applied."""
    merged = dict(instance_config)
    for key, value in overrides.items():
        if key in OVERRIDABLE_CONFIG_KEYS:
            merged[key] = value
    return merged


def read_instance_config(config_path: Path) -> dict[str, Any]:
    """Raw ``config.json``, or ``{}`` when it is missing or unreadable."""
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load config: %s", e)
        return {}


def active_config_workspace_id() -> str:
    """The workspace whose overrides the synchronous config paths should read.

    Inside a request this is the tenant's workspace. Outside one — the startup
    key migration, a script — there is no tenant, so it falls back to the
    instance default workspace. That fallback is safe because it is the
    *standalone* tenant (``tenant_ref = ""``), never a visitor's.
    """
    from app.database import db
    from app.tenancy import current_workspace_id

    return current_workspace_id() or db.default_workspace_id_sync()


def load_config(workspace_id: str | None = None) -> dict[str, Any]:
    """Load the merged configuration with a 5-minute TTL cache.

    Returns a deep copy so callers cannot corrupt the cached data.
    """
    from app.database import db

    if workspace_id is None:
        workspace_id = active_config_workspace_id()
    config_path = get_config_path()
    cache_key = (config_path, workspace_id)
    now = time.monotonic()
    cached = _config_cache.get(cache_key)
    if cached is not None and (now - _config_cache_time.get(cache_key, 0.0)) < (
        _CONFIG_CACHE_TTL
    ):
        return copy.deepcopy(cached)

    merged = read_instance_config(config_path)
    if workspace_id:
        merged = merge_workspace_overrides(
            merged, db.get_workspace_settings_sync(workspace_id)
        )
    _config_cache[cache_key] = merged
    _config_cache_time[cache_key] = now
    return copy.deepcopy(merged)


def get_content_language() -> str:
    """Get configured content language from cached config."""
    config = load_config()
    return config.get("content_language", config.get("language", "en"))
