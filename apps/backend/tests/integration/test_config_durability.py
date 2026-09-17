"""Config saves acknowledge replacement even when directory durability fails."""

import json
import logging
import os
import stat
from pathlib import Path
from typing import Literal

import pytest
from app.config import (
    get_api_keys_from_config,
    get_config_path,
    migrate_legacy_keys,
    save_config_file,
)
from app.config_cache import invalidate_config_cache, load_config
from app.database import Database


DirectoryOperation = Literal["open", "fsync", "close"]


def _fail_directory_operation(
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
    operation: DirectoryOperation,
) -> None:
    """Fail the directory operation while keeping file writes and cleanup real."""
    real_open, real_fsync, real_close = os.open, os.fsync, os.close

    def failing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if os.fspath(path) == str(directory):
            raise OSError("synthetic directory open failure")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    def failing_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic directory fsync failure")
        real_fsync(fd)

    def failing_close(fd: int) -> None:
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        # Model a close that releases the descriptor before reporting an error.
        real_close(fd)
        if is_directory:
            raise OSError("synthetic directory close failure")

    if operation == "open":
        monkeypatch.setattr(os, "open", failing_open)
    elif operation == "fsync":
        monkeypatch.setattr(os, "fsync", failing_fsync)
    else:
        monkeypatch.setattr(os, "close", failing_close)


@pytest.mark.skipif(os.name == "nt", reason="Directory fsync is a POSIX contract")
@pytest.mark.parametrize("failure", [None, "open", "fsync", "close"])
def test_committed_config_save_refreshes_cache_despite_directory_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: DirectoryOperation | None,
) -> None:
    """Cached readers must agree with the installed snapshot."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"enable_cover_letter": false}')
    assert load_config() == {"enable_cover_letter": False}
    if failure is not None:
        _fail_directory_operation(monkeypatch, path.parent, failure)

    with caplog.at_level(logging.WARNING, logger="app.config"):
        save_config_file({"enable_cover_letter": True})
    invalidate_config_cache()

    assert json.loads(path.read_text()) == {"enable_cover_letter": True}
    assert load_config() == {"enable_cover_letter": True}
    assert list(path.parent.glob(".config.json.*.tmp")) == []
    if failure is not None:
        assert any(
            record.name == "app.config"
            and record.exc_info is not None
            and f"synthetic directory {failure} failure" in str(record.exc_info[1])
            for record in caplog.records
        )


def test_file_fsync_failure_preserves_old_config_and_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-replacement durability failure remains a failed save."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"enable_cover_letter": false}')
    assert load_config() == {"enable_cover_letter": False}

    def fail_file_fsync(fd: int) -> None:
        assert stat.S_ISREG(os.fstat(fd).st_mode)
        raise OSError("synthetic file fsync failure")

    monkeypatch.setattr(os, "fsync", fail_file_fsync)
    with pytest.raises(OSError, match="synthetic file fsync failure"):
        save_config_file({"enable_cover_letter": True})

    assert json.loads(path.read_text()) == {"enable_cover_letter": False}
    assert load_config() == {"enable_cover_letter": False}
    assert list(path.parent.glob(".config.json.*.tmp")) == []


@pytest.mark.skipif(os.name == "nt", reason="Directory fsync is a POSIX contract")
@pytest.mark.parametrize("failure", ["open", "fsync", "close"])
def test_legacy_key_migration_completes_after_directory_durability_failure(
    isolated_backend_state: Database,
    monkeypatch: pytest.MonkeyPatch,
    failure: DirectoryOperation,
) -> None:
    """Startup migration can finish once the legacy plaintext is replaced."""
    workspace_id = isolated_backend_state.default_workspace_id_sync()
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"provider": "openai", "api_key": "synthetic-test-key"}')
    _fail_directory_operation(monkeypatch, path.parent, failure)

    migrate_legacy_keys()

    assert json.loads(path.read_text()) == {"provider": "openai"}
    assert get_api_keys_from_config(workspace_id) == {"openai": "synthetic-test-key"}
    migrate_legacy_keys()
    assert get_api_keys_from_config(workspace_id) == {"openai": "synthetic-test-key"}
