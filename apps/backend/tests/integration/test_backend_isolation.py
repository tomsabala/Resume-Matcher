"""Integration coverage for default test isolation and real startup key migration."""

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from app import crypto
from app.config import get_api_keys_from_config, settings
from app.main import app


def test_unstubbed_provider_connection_is_denied() -> None:
    """A provider socket cannot escape the deterministic backend test process."""
    with pytest.raises(RuntimeError, match="External network access blocked"):
        socket.create_connection(("api.openai.com", 443))


async def test_real_startup_migrates_legacy_api_keys(
    isolated_backend_state: Any,
    tmp_path: Path,
) -> None:
    """Real lifespan folds a plaintext config.json key into the encrypted store."""
    assert settings.data_dir == tmp_path / "data"
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    legacy_config_path = settings.config_path
    legacy_config_path.write_text(
        json.dumps(
            {
                "provider": "openai",
                "model": "synthetic-model",
                "api_key": "synthetic-legacy-key",
            }
        )
    )

    async with app.router.lifespan_context(app):
        workspace_id = await isolated_backend_state.default_workspace_id()
        assert get_api_keys_from_config(workspace_id) == {
            "openai": "synthetic-legacy-key"
        }
        assert crypto.decrypt(
            isolated_backend_state.get_api_key_ciphertexts(workspace_id)["openai"]
        ) == "synthetic-legacy-key"

    assert json.loads(legacy_config_path.read_text()) == {
        "provider": "openai",
        "model": "synthetic-model",
    }
