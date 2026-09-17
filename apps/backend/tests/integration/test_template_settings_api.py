"""Template and formatting settings belong to the resume.

They used to live only in the browser's localStorage, so the viewer and every
export rendered the defaults no matter what the builder was showing.
"""

import copy
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.document import ResumeDocument

from tests.integration.test_direct_improve_transactions import direct_case  # noqa: F401

TEX_SETTINGS: dict[str, Any] = {
    "settingsVersion": 2,
    "template": "tex-classic",
    "pageSize": "LETTER",
    "margins": {"top": 12, "bottom": 12, "left": 15, "right": 15},
    "spacing": {"section": 4, "item": 3, "bulletLeadIn": 9, "lineHeight": 6},
    "fontSize": {
        "base": 2,
        "headerScale": 4,
        "headerFont": "mono",
        "bodyFont": "serif",
    },
    "compactMode": True,
    "showContactIcons": True,
    "accentColor": "green",
}

# `TEX_SETTINGS` as the vocabulary that shipped before the spacing axes were
# widened to 1-9 would have stored it: no marker, every spacing level two
# steps lower, and no `bulletLeadIn` at all.
V1_SETTINGS: dict[str, Any] = {
    **{key: value for key, value in TEX_SETTINGS.items() if key != "settingsVersion"},
    "spacing": {"section": 2, "item": 1, "lineHeight": 4},
}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed(isolated_db: Any, sample_resume: dict[str, Any]) -> str:
    document = ResumeDocument.model_validate(copy.deepcopy(sample_resume)).model_dump(
        mode="json"
    )
    created = await isolated_db.create_resume(
        content="{}",
        content_type="document",
        processed_data=document,
        processing_status="ready",
        workspace_id=await isolated_db.default_workspace_id(),
    )
    return created["resume_id"]


async def test_a_saved_choice_comes_back_on_the_next_fetch(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        saved = await client.put(
            f"/api/v1/resumes/{resume_id}/template-settings", json=TEX_SETTINGS
        )
        fetched = await client.get(f"/api/v1/resumes?resume_id={resume_id}")

    assert saved.status_code == 200, saved.text
    assert saved.json() == TEX_SETTINGS
    assert fetched.json()["data"]["template_settings"] == TEX_SETTINGS


async def test_a_resume_with_no_choice_reports_none_rather_than_defaults(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """None is what lets the client keep its last-used settings; a defaulted
    payload would silently reset every pre-existing resume to swiss-single."""
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        fetched = await client.get(f"/api/v1/resumes?resume_id={resume_id}")

    assert fetched.json()["data"]["template_settings"] is None


async def test_a_row_stored_before_the_levels_widened_keeps_its_look(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """The spacing axes gained two steps at each end, so every stored level
    means what it used to mean two numbers higher up. Without the upgrade a
    resume designed yesterday opens two steps tighter than the user left it."""
    resume_id = await _seed(isolated_db, sample_resume)
    await isolated_db.update_resume(
        resume_id,
        {"template_settings": V1_SETTINGS},
        workspace_id=await isolated_db.default_workspace_id(),
    )

    async with _client() as client:
        fetched = await client.get(f"/api/v1/resumes?resume_id={resume_id}")

    assert fetched.json()["data"]["template_settings"] == {
        **TEX_SETTINGS,
        # Levels shifted +2; a v1 payload had no lead-in, so it takes the
        # neutral one, which is the gap `\parskip` used to leave on its own.
        "spacing": {"section": 4, "item": 3, "bulletLeadIn": 4, "lineHeight": 6},
    }



@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("template", "tex-retired"),
        ("pageSize", "A3"),
        ("accentColor", "purple"),
    ],
)
async def test_an_unrenderable_choice_is_rejected(
    isolated_db: Any, sample_resume: dict[str, Any], field: str, value: str
) -> None:
    """The stored value drives both PDF routes, so junk must not reach it."""
    resume_id = await _seed(isolated_db, sample_resume)
    payload = {**TEX_SETTINGS, field: value}

    async with _client() as client:
        response = await client.put(
            f"/api/v1/resumes/{resume_id}/template-settings", json=payload
        )
        fetched = await client.get(f"/api/v1/resumes?resume_id={resume_id}")

    assert response.status_code == 422
    assert fetched.json()["data"]["template_settings"] is None


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ({"margins": {"top": 40}}, "the print route clamps to 5-25mm"),
        ({"spacing": {"section": 10}}, "the spacing axes stop at 9"),
        ({"fontSize": {"base": 6}}, "the font axes stop at 5"),
    ],
)
async def test_out_of_range_formatting_is_rejected(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch: dict[str, dict[str, int]],
    reason: str,
) -> None:
    resume_id = await _seed(isolated_db, sample_resume)
    payload = copy.deepcopy(TEX_SETTINGS)
    for group, values in patch.items():
        payload[group].update(values)

    async with _client() as client:
        response = await client.put(
            f"/api/v1/resumes/{resume_id}/template-settings", json=payload
        )

    assert response.status_code == 422, reason


async def test_a_body_without_the_version_marker_is_rejected(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """A client still speaking the 1-5 vocabulary must be told so. Accepting
    its body would store every spacing level two steps tighter than the user
    chose, which nothing downstream could detect."""
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        response = await client.put(
            f"/api/v1/resumes/{resume_id}/template-settings", json=V1_SETTINGS
        )

    assert response.status_code == 422


async def test_saving_for_a_missing_resume_is_a_404(isolated_db: Any) -> None:
    async with _client() as client:
        response = await client.put(
            "/api/v1/resumes/does-not-exist/template-settings", json=TEX_SETTINGS
        )

    assert response.status_code == 404


async def test_a_document_edit_leaves_the_choice_alone(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """Presentation is not content: saving the document must not reset it."""
    resume_id = await _seed(isolated_db, sample_resume)
    document = ResumeDocument.model_validate(sample_resume).model_dump(mode="json")
    document["header"]["headline"] = "Changed headline"

    async with _client() as client:
        await client.put(
            f"/api/v1/resumes/{resume_id}/template-settings", json=TEX_SETTINGS
        )
        patched = await client.patch(f"/api/v1/resumes/{resume_id}", json=document)

    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["template_settings"] == TEX_SETTINGS


async def test_a_restore_does_not_revert_the_choice(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """The timeline carries documents, not presentation."""
    resume_id = await _seed(isolated_db, sample_resume)
    document = ResumeDocument.model_validate(sample_resume).model_dump(mode="json")

    async with _client() as client:
        assert (
            await client.patch(f"/api/v1/resumes/{resume_id}", json=document)
        ).status_code == 200
        versions = (await client.get(f"/api/v1/resumes/{resume_id}/versions")).json()
        version_id = versions["versions"][0]["version_id"]

        await client.put(
            f"/api/v1/resumes/{resume_id}/template-settings", json=TEX_SETTINGS
        )
        restored = await client.post(
            f"/api/v1/resumes/{resume_id}/restore", json={"version_id": version_id}
        )
        assert restored.status_code == 200, restored.text
        after = await client.get(f"/api/v1/resumes?resume_id={resume_id}")

    assert after.json()["data"]["template_settings"] == TEX_SETTINGS


async def test_a_tailored_resume_inherits_how_its_parent_looks(
    isolated_db: Any,
    direct_case: tuple[AsyncClient, dict[str, str]],
) -> None:
    """The user designed the parent; handing its tailoring a fresh default
    would silently change the template they chose."""
    client, payload = direct_case
    await client.put(
        f"/api/v1/resumes/{payload['resume_id']}/template-settings", json=TEX_SETTINGS
    )

    response = await client.post("/api/v1/resumes/improve", json=payload)

    assert response.status_code == 200, response.text
    tailored = await isolated_db.get_resume(
        response.json()["data"]["resume_id"],
        workspace_id=await isolated_db.default_workspace_id(),
    )
    assert tailored is not None
    assert tailored["template_settings"] == TEX_SETTINGS

