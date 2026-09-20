"""The gateway hop is authenticated: identity headers alone prove nothing.

``X-Apps-Tenant`` and ``X-Apps-Role`` are injected by an upstream gateway, but
nothing about an inbound request says it came from one. The backend is
reachable through the frontend's ``/api/:path*`` rewrite, which forwards
client headers verbatim, so "the proxy strips them" is a property of a config
file in another repository — not of this app.

These tests hold the line that makes that irrelevant:

* no secret, wrong secret, or no tenant → 404, whatever the role claims;
* a repeated identity header → 404, because an appending proxy would
  otherwise let the client's copy win the first-occurrence lookup;
* in ``single`` mode, any identity header at all → 404, which catches the
  deployment that turned the gateway on and forgot ``TENANT_MODE=header``.
"""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration

SECRET = "test-gateway-secret"
ATTACKER = "attacker-0000000000000000"
OPERATOR = "admin-cccc000000000000"


@pytest.fixture
def header_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "tenant_mode", "header")
    monkeypatch.setattr(settings, "gateway_secret", SECRET)


def _client(headers: list[tuple[str, str]]) -> AsyncClient:
    """A client whose headers are sent verbatim, duplicates included."""
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    )


# -- the secret -------------------------------------------------------------


async def test_a_forged_admin_without_the_secret_is_not_found(
    isolated_db: Any, header_mode: None
) -> None:
    async with _client(
        [("X-Apps-Tenant", ATTACKER), ("X-Apps-Role", "admin")]
    ) as client:
        assert (await client.get("/api/v1/resumes/list")).status_code == 404


async def test_a_wrong_secret_is_not_found(
    isolated_db: Any, header_mode: None
) -> None:
    async with _client(
        [
            ("X-Apps-Tenant", ATTACKER),
            ("X-Apps-Role", "admin"),
            ("X-Apps-Proxy-Secret", SECRET + "x"),
        ]
    ) as client:
        assert (await client.get("/api/v1/resumes/list")).status_code == 404


async def test_the_secret_alone_is_not_an_identity(
    isolated_db: Any, header_mode: None
) -> None:
    """A gateway that authenticated nobody still has to name the tenant."""
    async with _client([("X-Apps-Proxy-Secret", SECRET)]) as client:
        assert (await client.get("/api/v1/resumes/list")).status_code == 404


async def test_a_non_ascii_secret_is_refused_not_crashed(
    isolated_db: Any, header_mode: None
) -> None:
    """A high byte in the header must still be a 404.

    ``hmac.compare_digest`` raises ``TypeError`` on a non-ASCII ``str``, and
    the presented value is attacker-controlled — a 500 would confirm that
    something is listening.
    """
    async with _client(
        [
            ("X-Apps-Tenant", OPERATOR),
            ("X-Apps-Role", "admin"),
            # bytes, not str: httpx refuses to encode a non-ASCII header
            # value, but a raw socket client has no such scruples.
            ("X-Apps-Proxy-Secret", b"caf\xe9"),  # type: ignore[list-item]
        ]
    ) as client:
        assert (await client.get("/api/v1/resumes/list")).status_code == 404


async def test_the_full_gateway_triple_is_accepted(
    isolated_db: Any, header_mode: None
) -> None:
    async with _client(
        [
            ("X-Apps-Tenant", OPERATOR),
            ("X-Apps-Role", "admin"),
            ("X-Apps-Proxy-Secret", SECRET),
        ]
    ) as client:
        assert (await client.get("/api/v1/resumes/list")).status_code == 200


async def test_a_forged_admin_cannot_reach_the_instance_key(
    isolated_db: Any, header_mode: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The masked key used to be one header away — `admin` unlocks the env
    fallback, and `admin` was self-asserted."""
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "sk-operator-SECRET-value")
    async with _client(
        [("X-Apps-Tenant", ATTACKER), ("X-Apps-Role", "admin")]
    ) as client:
        response = await client.get("/api/v1/config/llm-api-key")
    assert response.status_code == 404
    assert "alue" not in response.text


# -- repeated headers -------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(
            [
                ("X-Apps-Role", "admin"),
                ("X-Apps-Tenant", OPERATOR),
                ("X-Apps-Proxy-Secret", SECRET),
                ("X-Apps-Role", "anon"),
            ],
            id="client-first",
        ),
        pytest.param(
            [
                ("X-Apps-Role", "anon"),
                ("X-Apps-Tenant", OPERATOR),
                ("X-Apps-Proxy-Secret", SECRET),
                ("X-Apps-Role", "admin"),
            ],
            id="gateway-first",
        ),
    ],
)
async def test_a_repeated_role_header_is_not_found(
    isolated_db: Any, header_mode: None, headers: list[tuple[str, str]]
) -> None:
    """Both orders 404. A proxy that appends instead of replacing leaves two
    values on the wire, and picking either one is a guess the attacker wins
    half the time."""
    async with _client(headers) as client:
        assert (await client.get("/api/v1/resumes/list")).status_code == 404


async def test_a_repeated_tenant_header_is_not_found(
    isolated_db: Any, header_mode: None
) -> None:
    async with _client(
        [
            ("X-Apps-Tenant", ATTACKER),
            ("X-Apps-Tenant", OPERATOR),
            ("X-Apps-Proxy-Secret", SECRET),
        ]
    ) as client:
        assert (await client.get("/api/v1/resumes/list")).status_code == 404


async def test_a_repeated_secret_header_is_not_found(
    isolated_db: Any, header_mode: None
) -> None:
    async with _client(
        [
            ("X-Apps-Tenant", OPERATOR),
            ("X-Apps-Proxy-Secret", "guess"),
            ("X-Apps-Proxy-Secret", SECRET),
        ]
    ) as client:
        assert (await client.get("/api/v1/resumes/list")).status_code == 404


# -- single mode ------------------------------------------------------------


async def test_single_mode_refuses_identity_headers(isolated_db: Any) -> None:
    """A private instance has no gateway, so these can only be a probe — or a
    live gateway in front of an instance that never got TENANT_MODE=header,
    which is the silent misconfiguration that shares one dataset."""
    async with _client([("X-Apps-Tenant", ATTACKER), ("X-Apps-Role", "admin")]) as c:
        assert (await c.get("/api/v1/resumes/list")).status_code == 404


async def test_single_mode_still_serves_an_ordinary_request(
    isolated_db: Any,
) -> None:
    async with _client([]) as client:
        assert (await client.get("/api/v1/resumes/list")).status_code == 200


async def test_single_mode_still_honours_the_workspace_header(
    isolated_db: Any,
) -> None:
    """``X-Workspace-Id`` is not an identity header: the profile switcher on a
    private instance must keep working."""
    workspace_id = await isolated_db.default_workspace_id()
    async with _client([("X-Workspace-Id", workspace_id)]) as client:
        assert (await client.get("/api/v1/resumes/list")).status_code == 200
