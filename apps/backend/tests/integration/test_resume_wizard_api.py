"""Integration tests for the adaptive resume wizard endpoints."""

import json
from typing import Any
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.database import Database
from app.main import app
from app.schemas.document import Bullet, Contact, Entry, Section, SectionKind, TagGroup
from app.schemas.resume_wizard import ResumeWizardHistoryEntry, ResumeWizardQuestion
from app.services.resume_wizard import (
    RESUME_WIZARD_MAX_QUESTIONS,
    build_initial_wizard_state,
)

_AI_RESULT = {
    "resume_data": {
        "schemaVersion": 2,
        "header": {"name": "James", "headline": "", "contacts": []},
        "sections": [
            {
                "key": "skills",
                "heading": "Skills & Awards",
                "kind": "groups",
                "groups": [{"label": "Technical Skills", "values": ["Python"]}],
            }
        ],
    },
    "next_question": {"text": "What tools do you use most?", "section": "section:skills"},
    "inferred_skills": ["FastAPI"],
    "is_complete": False,
}


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    """The section with this key in a serialized wizard state."""
    return next(
        section for section in payload["resume_data"]["sections"] if section["key"] == key
    )


async def test_turn_answer_runs_ai_and_returns_next_question(isolated_db) -> None:
    transport = ASGITransport(app=app)
    state = build_initial_wizard_state()
    state.step = "question"
    state.current_question.section = "section:skills"

    with patch(
        "app.services.resume_wizard.complete_json",
        new_callable=AsyncMock,
        return_value=_AI_RESULT,
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/resume-wizard/turn",
                json={
                    "state": state.model_dump(mode="json"),
                    "action": "answer",
                    "answer": {"text": "I use Python and FastAPI."},
                },
            )

    assert response.status_code == 200
    payload = response.json()["state"]
    assert payload["current_question"]["text"] == "What tools do you use most?"
    assert _section(payload, "skills")["groups"] == [
        {"label": "Technical Skills", "values": ["Python", "FastAPI"]}
    ]
    assert payload["asked_count"] == 1


async def test_turn_review_needs_no_llm(isolated_db) -> None:
    transport = ASGITransport(app=app)
    state = build_initial_wizard_state()
    state.step = "question"
    state.resume_data.header.name = "James"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resume-wizard/turn",
            json={"state": state.model_dump(mode="json"), "action": "review"},
        )

    assert response.status_code == 200
    payload = response.json()["state"]
    assert payload["step"] == "review"
    assert payload["warnings"]


async def test_turn_answer_without_answer_is_422(isolated_db) -> None:
    transport = ASGITransport(app=app)
    state = build_initial_wizard_state()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resume-wizard/turn",
            json={"state": state.model_dump(mode="json"), "action": "answer"},
        )
    assert response.status_code == 422


async def test_turn_malformed_model_envelope_is_recoverable_422(
    isolated_db: Database,
) -> None:
    transport = ASGITransport(app=app)
    state = build_initial_wizard_state()
    state.step = "question"
    state.current_question = ResumeWizardQuestion(
        text="Experience?", section="section:experience"
    )

    with patch(
        "app.services.resume_wizard.complete_json",
        new_callable=AsyncMock,
        return_value={"is_complete": "false"},
    ) as mock_complete:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/resume-wizard/turn",
                json={
                    "state": state.model_dump(mode="json"),
                    "action": "answer",
                    "answer": {"text": "Engineer at Acme"},
                },
            )

    assert response.status_code == 422
    assert response.json() == {"detail": "Could not update the resume draft."}
    assert mock_complete.await_count == 1


async def test_finalize_creates_ready_master_resume(isolated_db) -> None:
    transport = ASGITransport(app=app)
    state = build_initial_wizard_state()
    state.resume_data.header.name = "James"
    state.resume_data.header.contacts = [
        Contact(kind="email", value="james@example.com")
    ]
    state.resume_data.section("skills").groups = [
        TagGroup(label="Technical Skills", values=["Python"])
    ]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resume-wizard/finalize",
            json={"state": state.model_dump(mode="json")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "ready"
    assert payload["is_master"] is True

    workspace_id = await isolated_db.default_workspace_id()
    stored = await isolated_db.get_resume(payload["resume_id"], workspace_id=workspace_id)
    assert stored is not None
    assert stored["is_master"] is True
    assert stored["content_type"] == "json"
    content = json.loads(stored["content"])
    assert content["schemaVersion"] == 2
    assert content["header"]["name"] == "James"
    assert [c["value"] for c in content["header"]["contacts"]] == ["james@example.com"]


async def test_finalize_persists_a_user_created_section(isolated_db) -> None:
    """A section the six-section schema never had must survive finalize."""
    transport = ASGITransport(app=app)
    state = build_initial_wizard_state()
    state.resume_data.header.name = "James"
    state.resume_data.sections.append(
        Section(
            key="military_service",
            heading="Military Service",
            kind=SectionKind.ENTRIES,
            entries=[
                Entry(
                    title="Signals Officer",
                    subtitle="Signal Corps",
                    period="2016 - 2018",
                    summary="Ran the comms platoon.",
                    bullets=[Bullet(text="Led a team of eight")],
                )
            ],
        )
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resume-wizard/finalize",
            json={"state": state.model_dump(mode="json")},
        )

    assert response.status_code == 200
    workspace_id = await isolated_db.default_workspace_id()
    stored = await isolated_db.get_resume(
        response.json()["resume_id"], workspace_id=workspace_id
    )
    content = json.loads(stored["content"])
    military = next(s for s in content["sections"] if s["key"] == "military_service")
    assert military["heading"] == "Military Service"
    assert military["kind"] == "entries"
    assert military["entries"][0]["title"] == "Signals Officer"
    assert military["entries"][0]["summary"] == "Ran the comms platoon."
    assert military["entries"][0]["bullets"] == [
        {"text": "Led a team of eight", "style": "bullet"}
    ]


async def test_finalize_requires_a_name(isolated_db) -> None:
    transport = ASGITransport(app=app)
    state = build_initial_wizard_state()  # header.name is still empty

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resume-wizard/finalize",
            json={"state": state.model_dump(mode="json")},
        )

    assert response.status_code == 422
    assert "header.name is required" in json.dumps(response.json())


async def test_finalize_replays_identical_wizard_master_without_duplication(
    isolated_db: Database,
) -> None:
    state = build_initial_wizard_state()
    state.resume_data.header.name = "James"
    request = {"state": state.model_dump(mode="json")}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/v1/resume-wizard/finalize", json=request)
        replay = await client.post("/api/v1/resume-wizard/finalize", json=request)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["resume_id"] == first.json()["resume_id"]
    workspace_id = await isolated_db.default_workspace_id()
    assert len(await isolated_db.list_resumes(workspace_id)) == 1


async def test_finalize_rejects_different_draft_after_wizard_master_exists(
    isolated_db: Database,
) -> None:
    first_state = build_initial_wizard_state()
    first_state.resume_data.header.name = "James"
    changed_state = first_state.model_copy(deep=True)
    changed_state.resume_data.section("summary").text = "A different draft"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/v1/resume-wizard/finalize",
            json={"state": first_state.model_dump(mode="json")},
        )
        collision = await client.post(
            "/api/v1/resume-wizard/finalize",
            json={"state": changed_state.model_dump(mode="json")},
        )

    assert first.status_code == 200
    assert collision.status_code == 409
    workspace_id = await isolated_db.default_workspace_id()
    assert len(await isolated_db.list_resumes(workspace_id)) == 1


async def test_finalize_rejects_when_master_exists(isolated_db, sample_resume) -> None:
    workspace_id = await isolated_db.default_workspace_id()
    await isolated_db.create_resume(
        content=json.dumps(sample_resume),
        content_type="json",
        filename="existing.json",
        is_master=True,
        processed_data=sample_resume,
        processing_status="ready",
        workspace_id=workspace_id,
    )
    state = build_initial_wizard_state()
    state.resume_data.header.name = "James"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resume-wizard/finalize",
            json={"state": state.model_dump(mode="json")},
        )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


async def test_turn_start_returns_initial_state(isolated_db) -> None:
    transport = ASGITransport(app=app)
    state = build_initial_wizard_state()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resume-wizard/turn",
            json={"state": state.model_dump(mode="json"), "action": "start"},
        )

    assert response.status_code == 200
    payload = response.json()["state"]
    assert payload["step"] == "intro"
    assert payload["current_question"]["section"] == "intro"
    assert payload["asked_count"] == 0
    # The wizard hands the client a shaped document, not an empty blob.
    assert [s["key"] for s in payload["resume_data"]["sections"]] == [
        "summary",
        "experience",
        "education",
        "projects",
        "skills",
    ]


async def test_turn_back_restores_previous_question(isolated_db) -> None:
    transport = ASGITransport(app=app)
    state = build_initial_wizard_state()
    state.step = "question"
    state.asked_count = 1
    state.current_question = ResumeWizardQuestion(text="Skills?", section="section:skills")
    state.resume_data.section("skills").groups = [
        TagGroup(label="Technical Skills", values=["Python"])
    ]
    state.history = [
        ResumeWizardHistoryEntry(
            question="Where have you worked?",
            answer="Acme",
            section="section:experience",
            resume_data_before=build_initial_wizard_state().resume_data,
        )
    ]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resume-wizard/turn",
            json={"state": state.model_dump(mode="json"), "action": "back"},
        )

    assert response.status_code == 200
    payload = response.json()["state"]
    assert payload["asked_count"] == 0
    assert payload["current_question"]["section"] == "section:experience"
    # The pre-answer snapshot is restored, dropping the later skills edit.
    assert _section(payload, "skills")["groups"] == []


async def test_turn_skip_advances_without_modifying_resume_data(isolated_db) -> None:
    transport = ASGITransport(app=app)
    state = build_initial_wizard_state()
    state.step = "question"
    state.current_question = ResumeWizardQuestion(
        text="Education?", section="section:education"
    )

    skip_result = {
        "resume_data": {
            "schemaVersion": 2,
            "sections": [
                {
                    "key": "education",
                    "heading": "Education",
                    "kind": "entries",
                    "entries": [{"title": "MIT"}],
                }
            ],
        },
        "next_question": {"text": "What skills?", "section": "section:skills"},
        "inferred_skills": [],
        "is_complete": False,
    }
    with patch(
        "app.services.resume_wizard.complete_json",
        new_callable=AsyncMock,
        return_value=skip_result,
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/resume-wizard/turn",
                json={"state": state.model_dump(mode="json"), "action": "skip"},
            )

    assert response.status_code == 200
    payload = response.json()["state"]
    assert payload["current_question"]["section"] == "section:skills"
    # skip must not apply the model's data
    assert _section(payload, "education")["entries"] == []
    assert payload["asked_count"] == 1


async def test_turn_answer_past_cap_routes_to_review_without_llm(isolated_db) -> None:
    transport = ASGITransport(app=app)
    state = build_initial_wizard_state()
    state.step = "question"
    state.current_question.section = "section:skills"
    state.asked_count = RESUME_WIZARD_MAX_QUESTIONS  # at the cap

    with patch(
        "app.services.resume_wizard.complete_json",
        new_callable=AsyncMock,
    ) as mock_complete:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/resume-wizard/turn",
                json={
                    "state": state.model_dump(mode="json"),
                    "action": "answer",
                    "answer": {"text": "one more thing"},
                },
            )

    assert response.status_code == 200
    assert response.json()["state"]["step"] == "review"
    mock_complete.assert_not_awaited()  # cap guard must skip the LLM call
