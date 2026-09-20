"""Application configuration using pydantic-settings."""

import json
import logging
import os
import stat
import tempfile
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ALLOWED_LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")
logger = logging.getLogger(__name__)
_CONFIG_WRITE_LOCK = threading.Lock()


def get_config_path() -> Path:
    """Return the canonical config path, honoring legacy monkeypatches.

    ``settings.config_path`` owns the runtime location. ``CONFIG_FILE_PATH`` is
    retained as a compatibility alias for existing callers that monkeypatch
    that name; only an explicit change from its import-time value wins over the
    Settings-owned path.
    """
    if CONFIG_FILE_PATH != _IMPORTED_CONFIG_FILE_PATH:
        return CONFIG_FILE_PATH
    return settings.config_path


def _read_config_json() -> dict[str, Any]:
    """Raw read of config.json (no key injection)."""
    config_path = get_config_path()
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_config_json(config: dict[str, Any]) -> None:
    """Atomically replace config.json with one complete snapshot.

    Writes are serialized within the process. Callers provide complete
    snapshots, so concurrent in-process updates resolve in lock-acquisition
    order. Cross-process writers still install only complete snapshots because
    replacement is atomic. In both cases the last completed replacement wins;
    this primitive does not merge fields. Directory durability errors after
    replacement are logged: the snapshot is already installed, so callers must
    still acknowledge the save and invalidate cached reads.
    """
    serialized = json.dumps(config, indent=2)
    with _CONFIG_WRITE_LOCK:
        # Follow managed symlinks instead of replacing the link itself. Keep an
        # existing target's access mode; new configurations remain owner-only.
        config_path = get_config_path().resolve()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        existing_mode = (
            stat.S_IMODE(config_path.stat().st_mode) if config_path.exists() else None
        )
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            if existing_mode is not None:
                os.chmod(temporary_path, existing_mode)
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
                file_descriptor = -1
                temporary_file.write(serialized)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, config_path)
            if os.name != "nt":
                try:
                    directory_fd = os.open(
                        config_path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                    )
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                except OSError:
                    logger.warning(
                        "Config snapshot replaced at %s, but directory durability "
                        "could not be confirmed",
                        config_path,
                        exc_info=True,
                    )
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            temporary_path.unlink(missing_ok=True)


def load_config_file(workspace_id: str | None = None) -> dict[str, Any]:
    """Load one workspace's merged configuration, with its API keys injected.

    Three layers, outermost last: ``config.json`` (instance default), the
    workspace's ``workspace_settings`` overrides, then its decrypted API keys
    under ``api_keys``. Keys live in the encrypted SQLite store, not
    ``config.json``, and are injected here so ``resolve_api_key(stored,
    provider)`` keeps resolving per-provider keys everywhere ``stored`` is
    built from this function. ``save_config_file`` strips them again, so they
    never round-trip back to disk.

    ``workspace_id`` defaults to the request's workspace, or to the instance
    default one outside a request — see ``config_cache`` for why that fallback
    cannot reach a visitor's data.
    """
    from app.config_cache import (
        active_config_workspace_id,
        merge_workspace_overrides,
    )
    from app.database import db

    if workspace_id is None:
        workspace_id = active_config_workspace_id()
    config = _read_config_json()
    if workspace_id:
        config = merge_workspace_overrides(
            config, db.get_workspace_settings_sync(workspace_id)
        )
    config["api_keys"] = get_api_keys_from_config(workspace_id)
    return config


def save_config_file(config: dict[str, Any]) -> None:
    """Save non-secret configuration to config.json.

    Secrets (``api_keys`` map and the legacy single ``api_key``) are stripped
    before writing — they belong to the encrypted store only.
    """
    config = dict(config)
    config.pop("api_keys", None)
    config.pop("api_key", None)
    _write_config_json(config)


def get_api_keys_from_config(workspace_id: str) -> dict[str, str]:
    """Get one workspace's decrypted API keys from the encrypted SQLite store.

    Returns:
        Dictionary with key-store provider names as keys and plaintext keys as
        values (entries that fail to decrypt are omitted).
    """
    from app.crypto import decrypt
    from app.database import db

    decrypted: dict[str, str] = {}
    if not workspace_id:
        return decrypted
    for provider, ciphertext in db.get_api_key_ciphertexts(workspace_id).items():
        plaintext = decrypt(ciphertext)
        if plaintext:
            decrypted[provider] = plaintext
    return decrypted


def save_api_keys_to_config(api_keys: dict[str, str], workspace_id: str) -> None:
    """Replace one workspace's encrypted key store with ``api_keys``.

    Replace-all semantics mirror the legacy ``config["api_keys"] = api_keys``;
    the config router reads-merges-saves the full map.
    """
    from app.crypto import encrypt
    from app.database import db

    # Encrypt everything first, then swap in a single transaction, so a partial
    # failure (encryption error or DB write) can never wipe previously stored
    # keys mid-replace.
    ciphertexts = {provider: encrypt(key) for provider, key in api_keys.items() if key}
    db.replace_api_keys(workspace_id, ciphertexts)


def delete_api_key_from_config(provider: str, workspace_id: str) -> None:
    """Delete a specific API key from one workspace's encrypted store."""
    from app.database import db

    db.delete_api_key(workspace_id, provider)


def clear_all_api_keys(workspace_id: str) -> None:
    """Clear one workspace's API keys and any legacy config slots.

    The legacy plaintext remnants in ``config.json`` are instance-wide, so
    clearing them is only correct for the standalone tenant — a visitor
    clearing their own keys must not rewrite the operator's file.
    """
    from app.database import db

    db.clear_api_keys(workspace_id)
    if workspace_id != _instance_default_workspace_id():
        return
    config = _read_config_json()
    if "api_keys" in config or "api_key" in config:
        config.pop("api_keys", None)
        config.pop("api_key", None)
        _write_config_json(config)


def _instance_default_workspace_id() -> str:
    """The standalone tenant's default workspace, or ``""`` if unseeded."""
    from app.database import db

    return db.default_workspace_id_sync()


def migrate_legacy_keys() -> None:
    """Fold legacy plaintext keys from config.json into the encrypted store.

    Idempotent and non-clobbering: an existing config.json ``api_keys`` map and
    the legacy single ``api_key`` (mapped to its key-store provider via the
    active provider) are written to the encrypted store **only if that provider
    slot is empty**, then removed from config.json. This eliminates the
    legacy-shadow bug where ``resolve_api_key`` returned one shared key for
    every provider.

    An instance-level one-shot, run once from the lifespan: the keys came out
    of the operator's own file, so they land in the standalone tenant's default
    workspace — the one ``CLAIM_TENANT_REF`` later transfers to the operator.
    They are never handed to a visitor.
    """
    config = _read_config_json()
    legacy_map = config.get("api_keys")
    legacy_single = config.get("api_key")
    if not legacy_map and not legacy_single:
        return

    from app.crypto import encrypt
    from app.database import db

    workspace_id = _instance_default_workspace_id()
    if not workspace_id:
        logger.warning(
            "Legacy API keys are present but no default workspace exists yet; "
            "leaving config.json untouched so the next startup can migrate them"
        )
        return
    existing = set(db.get_api_key_ciphertexts(workspace_id).keys())

    if isinstance(legacy_map, dict):
        for provider, key in legacy_map.items():
            if key and provider not in existing:
                db.set_api_key_ciphertext(workspace_id, provider, encrypt(key))
                existing.add(provider)

    if legacy_single:
        # Map the active LLM provider to its key-store provider name.
        provider = config.get("provider") or settings.llm_provider
        key_provider = _LEGACY_PROVIDER_KEY_MAP.get(provider, provider)
        if key_provider not in existing:
            db.set_api_key_ciphertext(
                workspace_id, key_provider, encrypt(legacy_single)
            )

    # Strip the legacy slots from config.json now that they're in the store.
    config.pop("api_keys", None)
    config.pop("api_key", None)
    _write_config_json(config)


# Mirror of llm._PROVIDER_KEY_MAP, duplicated to avoid importing llm.py (which
# pulls in litellm) at config import time.
_LEGACY_PROVIDER_KEY_MAP: dict[str, str] = {
    "openai": "openai",
    "openai_compatible": "openai_compatible",
    "azure_foundry": "azure_foundry",
    "anthropic": "anthropic",
    "gemini": "google",
    "openrouter": "openrouter",
    "deepseek": "deepseek",
    "groq": "groq",
    "ollama": "ollama",
}


def _get_llm_api_key_with_fallback() -> str:
    """Get LLM API key with fallback to the active workspace's key store.

    Priority: Environment variable > the caller's stored key > empty string.
    """
    import os

    from app.config_cache import active_config_workspace_id

    # First check environment variable
    env_key = os.environ.get("LLM_API_KEY", "")
    if env_key:
        return env_key

    # Fall back to the caller's own stored key, never another tenant's.
    config_keys = get_api_keys_from_config(active_config_workspace_id())
    provider = os.environ.get("LLM_PROVIDER", "openai")

    # Map provider to config key
    provider_map = {
        "openai": "openai",
        "azure_foundry": "azure_foundry",
        "anthropic": "anthropic",
        "gemini": "google",
        "openrouter": "openrouter",
        "deepseek": "deepseek",
        "groq": "groq",
        "ollama": "ollama",
    }

    config_provider = provider_map.get(provider, provider)
    return config_keys.get(config_provider, "")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Configuration
    llm_provider: Literal[
        "openai",
        "openai_compatible",
        "azure_foundry",
        "anthropic",
        "openrouter",
        "gemini",
        "deepseek",
        "groq",
        "ollama",
    ] = "openai"
    llm_model: str = "gpt-5-nano-2025-08-07"
    llm_api_key: str = ""
    llm_api_base: str | None = None  # For Ollama or custom endpoints
    log_llm: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "WARNING"

    @field_validator("llm_provider", mode="before")
    @classmethod
    def set_default_provider(cls, v: Any) -> str:
        """Handle empty string provider by defaulting to openai."""
        if not v or (isinstance(v, str) and not v.strip()):
            return "openai"
        return v

    @field_validator("log_llm", mode="before")
    @classmethod
    def normalize_log_llm_level(cls, v: Any) -> str:
        """Normalize LiteLLM log level from environment values."""
        value = "WARNING" if not v else str(v).strip().upper()
        if value not in ALLOWED_LOG_LEVELS:
            raise ValueError(f"Invalid LOG_LLM: {value}. Allowed: {ALLOWED_LOG_LEVELS}")
        return value

    # Multi-tenancy. ``single`` is the private, single-user instance: one
    # implicit tenant (``tenant_ref = ""``), admin role, the ``LLM_API_KEY``
    # env fallback allowed, and identity headers rejected outright. ``header``
    # trusts an authenticating gateway to inject ``X-Apps-Tenant`` /
    # ``X-Apps-Role`` *and* the shared secret below on every proxied request,
    # and 404s any ``/api/**`` call that arrives without them.
    #
    # There is deliberately NO default. The two modes have opposite security
    # postures, and the dangerous mistake — shipping a shared deployment that
    # silently fell back to ``single``, where every visitor is the admin of one
    # shared dataset — is exactly what a default produces. Refusing to start is
    # the only answer that cannot be missed.
    tenant_mode: Literal["single", "header"]

    #: The secret the gateway presents as ``X-Apps-Proxy-Secret``. Required in
    #: ``header`` mode: without it ``X-Apps-Role: admin`` is self-asserted, and
    #: anyone who can reach the app claims the operator's workspaces and spends
    #: the operator's ``LLM_API_KEY``. Unused in ``single`` mode.
    gateway_secret: str = ""

    #: One-shot ownership transfer for an instance flipped from ``single`` to
    #: ``header``: on startup, every still-unowned workspace (``tenant_ref =
    #: ""``) is stamped with this tenant ref. Set it to the operator's own
    #: ``X-Apps-Tenant`` value, run once, then remove it. Empty means "claim
    #: nothing"; the transfer is never triggered by an inbound request.
    claim_tenant_ref: str = ""

    @model_validator(mode="before")
    @classmethod
    def surface_missing_tenant_mode(cls, data: Any) -> Any:
        """Turn an absent ``TENANT_MODE`` into the field validator's error.

        A required field that is simply missing yields pydantic's generic
        "Field required", which tells an operator nothing about what to
        choose. Substituting an empty value routes it through
        :meth:`validate_tenant_mode`, which explains both options.
        """
        if isinstance(data, dict) and not any(
            str(key).lower() == "tenant_mode" for key in data
        ):
            return {**data, "tenant_mode": ""}
        return data

    @field_validator("tenant_mode", mode="before")
    @classmethod
    def validate_tenant_mode(cls, v: Any) -> str:
        """Reject a blank or misspelled ``TENANT_MODE`` instead of guessing.

        ``TENANT_MODE=heder`` used to normalize to ``single``, which is the
        fail-open direction: the operator believes the instance is isolating
        tenants and it is not.
        """
        value = str(v).strip().lower() if v is not None else ""
        if value not in ("single", "header"):
            raise ValueError(
                "TENANT_MODE must be set explicitly to 'single' (a private, "
                "single-user instance) or 'header' (behind an authenticating "
                f"gateway); got {v!r}."
            )
        return value

    @field_validator("gateway_secret", mode="before")
    @classmethod
    def strip_gateway_secret(cls, v: Any) -> str:
        """Trim the secret, and keep it ASCII.

        It is compared against a header value, which arrives as bytes and is
        decoded latin-1; a non-ASCII secret could therefore never match what
        the gateway sent. Every generated secret (hex, base64, uuid) is ASCII,
        so refusing one is cheaper than a mismatch nobody can debug.
        """
        secret = "" if v is None else str(v).strip()
        if not secret.isascii():
            raise ValueError("GATEWAY_SECRET must be ASCII (e.g. `openssl rand -hex 32`).")
        return secret

    @model_validator(mode="after")
    def require_gateway_secret_in_header_mode(self) -> "Settings":
        """``header`` mode without a shared secret is not authenticated at all."""
        if self.tenant_mode == "header" and not self.gateway_secret:
            raise ValueError(
                "TENANT_MODE=header requires GATEWAY_SECRET: the identity "
                "headers are unauthenticated without it, so any client could "
                "present X-Apps-Role: admin. Set the same value on the gateway."
            )
        if self.claim_tenant_ref and self.tenant_mode != "header":
            raise ValueError(
                "CLAIM_TENANT_REF only applies to TENANT_MODE=header."
            )
        return self

    # How long an anonymous tenant's data survives without a request. The
    # hourly purge in the lifespan deletes idle anonymous workspaces outright;
    # admin tenants are never purged. Only consulted in ``header`` mode.
    anonymous_retention_hours: int = Field(default=24, ge=1, le=8760)

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    frontend_base_url: str = "http://localhost:3000"

    # Total timeout for AI operations, including validation, database preloads,
    # model attempts and persistence. Nested stages share one deadline. It MUST be
    # kept in sync with the two frontend layers (Next.js `proxyTimeout` and the
    # client AbortController, both driven by NEXT_PUBLIC_REQUEST_TIMEOUT_MS):
    # whichever layer is shortest aborts first, so raising only one silently fails
    # (this is why issue #776's backend-only workaround didn't work). Local LLMs
    # (Ollama, llama.cpp, …) often need longer than the 240s default; bounded to
    # [30, 1800]s so a stuck request can't hold a worker indefinitely.
    request_timeout_seconds: int = 240
    preview_ttl_seconds: int = Field(default=86400, ge=60, le=604800)

    @field_validator("preview_ttl_seconds", mode="before")
    @classmethod
    def clamp_preview_ttl(cls, value: Any) -> int:
        """Keep invalid preview-lifetime settings from preventing startup."""
        try:
            seconds = int(float(str(value).strip()))
        except (TypeError, ValueError, OverflowError):
            return 86400
        return max(60, min(604800, seconds))

    # Builder autosave fires on every pause, so consecutive manual saves inside
    # this window replace the previous version in place instead of stacking
    # hundreds of near-identical rows. AI, import, wizard, restore and tex_edit
    # origins never coalesce — each is a deliberate checkpoint.
    resume_version_coalesce_seconds: int = Field(default=300, ge=0, le=3600)

    @field_validator("resume_version_coalesce_seconds", mode="before")
    @classmethod
    def clamp_version_coalesce(cls, value: Any) -> int:
        """Keep an invalid coalescing window from preventing startup."""
        try:
            seconds = int(float(str(value).strip()))
        except (TypeError, ValueError, OverflowError):
            return 300
        return max(0, min(3600, seconds))

    @field_validator("request_timeout_seconds", mode="before")
    @classmethod
    def clamp_request_timeout(cls, v: Any) -> int:
        """Clamp to [30, 1800] seconds; fall back to 240 on blank/invalid input."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return 240
        try:
            seconds = int(float(str(v).strip()))
        except (TypeError, ValueError, OverflowError):
            # OverflowError guards against inf (int(float("inf"))); ValueError
            # against nan/garbage. A bad env value must never crash startup.
            return 240
        return max(30, min(1800, seconds))

    # Reasoning effort for models that support it (OpenAI gpt-5 family,
    # Anthropic Claude 3.7+, DeepSeek R1, etc.). None means "do not send the
    # param" — the default for maximum compatibility. LiteLLM drops this
    # parameter for providers that don't support it (via drop_params=True).
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None

    @field_validator("reasoning_effort", mode="before")
    @classmethod
    def normalize_reasoning_effort(cls, v: Any) -> Any:
        """Treat empty string (common when env var is blank) as None."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, v: Any) -> str:
        """Normalize application log level from environment values."""
        value = "INFO" if not v else str(v).strip().upper()
        if value not in ALLOWED_LOG_LEVELS:
            raise ValueError(f"Invalid LOG_LEVEL: {value}. Allowed: {ALLOWED_LOG_LEVELS}")
        return value

    # CORS Configuration
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @property
    def effective_cors_origins(self) -> list[str]:
        """CORS origins including frontend_base_url for production deployments."""
        origins = list(self.cors_origins)
        url = self.frontend_base_url.strip().rstrip("/")
        if url and url not in origins:
            origins.append(url)
        return origins

    # Paths
    data_dir: Path = Path(__file__).parent.parent / "data"

    @property
    def db_path(self) -> Path:
        """Path to the legacy TinyDB database file (migration source only)."""
        return self.data_dir / "database.json"

    @property
    def sqlite_path(self) -> Path:
        """Path to the SQLite database file (primary data store)."""
        return self.data_dir / "resume_matcher.db"

    @property
    def config_path(self) -> Path:
        """Path to config storage file."""
        return self.data_dir / "config.json"

    def get_effective_api_key(self) -> str:
        """Get the effective API key with config file fallback.

        Priority: Environment/settings value > config.json > empty string
        """
        if self.llm_api_key:
            return self.llm_api_key
        return _get_llm_api_key_with_fallback()


settings = Settings()

# Deprecated compatibility alias. Runtime config I/O is owned by
# ``settings.config_path`` through ``get_config_path``; downstream tests and
# integrations that explicitly monkeypatch this name continue to work.
CONFIG_FILE_PATH = settings.config_path
_IMPORTED_CONFIG_FILE_PATH = CONFIG_FILE_PATH
