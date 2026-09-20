"""``TENANT_MODE`` is a security posture, so it is declared, never inferred.

The two modes are opposites: ``single`` authenticates nobody and hands every
caller the admin role over one shared dataset, ``header`` isolates tenants
behind a gateway. A default — or a validator that quietly rounded a typo down
to ``single`` — makes the dangerous one the accident.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class TestTenantModeIsExplicit:
    def test_it_has_no_default(self) -> None:
        assert Settings.model_fields["tenant_mode"].is_required()

    def test_a_missing_value_is_refused_with_both_options(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TENANT_MODE", raising=False)
        with pytest.raises(ValidationError, match="TENANT_MODE must be set"):
            Settings(_env_file=None)

    @pytest.mark.parametrize("value", ["", "   ", "heder", "multi", "true"])
    def test_a_blank_or_misspelled_value_is_refused(self, value: str) -> None:
        with pytest.raises(ValidationError, match="TENANT_MODE must be set"):
            Settings(tenant_mode=value)

    @pytest.mark.parametrize(
        ("given", "expected"), [("single", "single"), (" Header ", "header")]
    )
    def test_a_recognised_value_is_normalised(self, given: str, expected: str) -> None:
        secret = {"gateway_secret": "s"} if expected == "header" else {}
        assert Settings(tenant_mode=given, **secret).tenant_mode == expected


class TestHeaderModeRequiresASecret:
    def test_header_without_a_secret_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="requires GATEWAY_SECRET"):
            Settings(tenant_mode="header", gateway_secret="")

    def test_a_whitespace_only_secret_is_no_secret(self) -> None:
        with pytest.raises(ValidationError, match="requires GATEWAY_SECRET"):
            Settings(tenant_mode="header", gateway_secret="   ")

    def test_header_with_a_secret_starts(self) -> None:
        settings = Settings(tenant_mode="header", gateway_secret=" s3cret ")
        assert settings.gateway_secret == "s3cret"

    def test_a_non_ascii_secret_is_refused(self) -> None:
        """It is compared against a latin-1-decoded header, so it could never
        match — and `hmac.compare_digest` raises on non-ASCII `str`."""
        with pytest.raises(ValidationError, match="must be ASCII"):
            Settings(tenant_mode="header", gateway_secret="café")

    def test_single_mode_needs_no_secret(self) -> None:
        assert Settings(tenant_mode="single").gateway_secret == ""


class TestClaimTenantRef:
    def test_it_is_refused_outside_header_mode(self) -> None:
        with pytest.raises(ValidationError, match="CLAIM_TENANT_REF"):
            Settings(tenant_mode="single", claim_tenant_ref="admin-1")

    def test_it_is_accepted_in_header_mode(self) -> None:
        settings = Settings(
            tenant_mode="header", gateway_secret="s", claim_tenant_ref="admin-1"
        )
        assert settings.claim_tenant_ref == "admin-1"


def _docs_urls(tenant_mode: str) -> tuple[object, object, object]:
    """Import ``app.main`` in a clean process and report its docs routes.

    Subprocess rather than ``importlib.reload``: the docs decision is made
    when the ``FastAPI`` object is constructed, and reloading the module in
    this process would leave other tests holding a stale ``app``.
    """
    env = {
        **os.environ,
        "TENANT_MODE": tenant_mode,
        "GATEWAY_SECRET": "s3cret",
    }
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.main import app;"
            " print(app.docs_url, app.redoc_url, app.openapi_url)",
        ],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    return tuple(result.stdout.strip().split())  # type: ignore[return-value]


class TestDocsExposure:
    """``/docs``, ``/redoc`` and ``/openapi.json`` are exempt from tenancy, so
    on a shared instance they publish the whole endpoint inventory to anyone
    who can reach the app. A private instance keeps them."""

    def test_header_mode_serves_no_docs(self) -> None:
        assert _docs_urls("header") == ("None", "None", "None")

    def test_single_mode_keeps_the_docs(self) -> None:
        assert _docs_urls("single") == ("/docs", "/redoc", "/openapi.json")
