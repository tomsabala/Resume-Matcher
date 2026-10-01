"""Integration tests for the interview-prep flashcard API (real isolated DB)."""

from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas import PrepCardAnswer, PrepCardCritique, PrepCardProposal


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _create(client, **payload):
    body = {"category": "technical", "question": "Explain SQLite WAL mode."}
    body.update(payload)
    resp = await client.post("/api/v1/prep-cards", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _seed_master_resume(isolated_db):
    workspace_id = await isolated_db.default_workspace_id()
    resume = await isolated_db.create_resume(
        content="# Resume",
        is_master=True,
        processed_data={"header": {"name": "Tom"}, "sections": []},
        processing_status="ready",
        workspace_id=workspace_id,
    )
    return workspace_id, resume


class TestCrud:
    async def test_create_list_patch_delete_round_trip(self, isolated_db):
        async with _client() as client:
            created = await _create(client)
            assert created["confidence"] == "unrated"
            assert created["source"] == "manual"
            assert created["answer"] is None

            listed = await client.get("/api/v1/prep-cards")
            assert [c["card_id"] for c in listed.json()["cards"]] == [created["card_id"]]

            patched = await client.patch(
                f"/api/v1/prep-cards/{created['card_id']}",
                json={"question": "Explain WAL.", "answer": "A write-ahead log."},
            )
            assert patched.status_code == 200
            assert patched.json()["question"] == "Explain WAL."
            assert patched.json()["answer"] == "A write-ahead log."

            deleted = await client.delete(f"/api/v1/prep-cards/{created['card_id']}")
            assert deleted.status_code == 200
            assert deleted.json()["affected"] == 1

            listed = await client.get("/api/v1/prep-cards")
            assert listed.json()["cards"] == []

    async def test_category_query_filters(self, isolated_db):
        async with _client() as client:
            technical = await _create(client, category="technical")
            personal = await _create(client, category="personal", question="Why this role?")

            only_technical = await client.get("/api/v1/prep-cards?category=technical")
            assert [c["card_id"] for c in only_technical.json()["cards"]] == [
                technical["card_id"]
            ]

            only_personal = await client.get("/api/v1/prep-cards?category=personal")
            assert [c["card_id"] for c in only_personal.json()["cards"]] == [
                personal["card_id"]
            ]

    async def test_rating_a_card_stamps_reviewed_at(self, isolated_db):
        """Nothing else writes ``reviewed_at``: a rating *is* the review event."""
        async with _client() as client:
            created = await _create(client)
            assert created["reviewed_at"] is None

            rated = await client.patch(
                f"/api/v1/prep-cards/{created['card_id']}", json={"confidence": "good"}
            )
            assert rated.json()["confidence"] == "good"
            assert rated.json()["reviewed_at"] is not None

    async def test_patch_without_confidence_leaves_reviewed_at_alone(self, isolated_db):
        async with _client() as client:
            created = await _create(client)
            patched = await client.patch(
                f"/api/v1/prep-cards/{created['card_id']}", json={"question": "New?"}
            )
            assert patched.json()["reviewed_at"] is None

    async def test_unknown_card_is_404_on_every_verb(self, isolated_db):
        async with _client() as client:
            assert (await client.get("/api/v1/prep-cards/nope")).status_code == 404
            patched = await client.patch(
                "/api/v1/prep-cards/nope", json={"confidence": "good"}
            )
            assert patched.status_code == 404
            assert (await client.delete("/api/v1/prep-cards/nope")).status_code == 404

    async def test_bulk_create_returns_every_card(self, isolated_db):
        async with _client() as client:
            resp = await client.post(
                "/api/v1/prep-cards/bulk-create",
                json={
                    "cards": [
                        {"category": "technical", "question": "What is a B-tree?"},
                        {"category": "personal", "question": "Why did you leave?"},
                    ]
                },
            )
            assert resp.status_code == 200, resp.text
            cards = resp.json()["cards"]
            assert len(cards) == 2
            assert {c["category"] for c in cards} == {"technical", "personal"}
            # Accepted proposals are provenance-tagged, not "manual".
            assert {c["source"] for c in cards} == {"generated"}

            listed = await client.get("/api/v1/prep-cards")
            assert len(listed.json()["cards"]) == 2

    async def test_bulk_delete_counts_only_real_rows(self, isolated_db):
        async with _client() as client:
            first = await _create(client)
            second = await _create(client, question="What is fsync?")
            resp = await client.post(
                "/api/v1/prep-cards/bulk-delete",
                json={"card_ids": [first["card_id"], second["card_id"], "ghost"]},
            )
            assert resp.json()["affected"] == 2
            listed = await client.get("/api/v1/prep-cards")
            assert listed.json()["cards"] == []

    async def test_cards_are_scoped_to_their_workspace(self, isolated_db):
        other = await isolated_db.create_workspace(name="Other")
        async with _client() as client:
            created = await _create(client)
            listed = await client.get(
                "/api/v1/prep-cards", headers={"X-Workspace-Id": other["workspace_id"]}
            )
            assert listed.json()["cards"] == []
            fetched = await client.get(
                f"/api/v1/prep-cards/{created['card_id']}",
                headers={"X-Workspace-Id": other["workspace_id"]},
            )
            assert fetched.status_code == 404


class TestGenerate:
    async def test_generate_returns_proposals_without_persisting(self, isolated_db):
        await _seed_master_resume(isolated_db)
        proposals = [
            PrepCardProposal(category="technical", question="What is WAL?", explanation="x")
        ]
        with patch(
            "app.routers.prep_cards.generate_prep_cards",
            new_callable=AsyncMock,
            return_value=proposals,
        ):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/prep-cards/generate",
                    json={"category": "technical", "count": 1},
                )
                assert resp.status_code == 200, resp.text
                assert resp.json()["proposals"][0]["question"] == "What is WAL?"
                # A proposal is not a card until the user accepts it.
                listed = await client.get("/api/v1/prep-cards")
                assert listed.json()["cards"] == []

    async def test_generate_requires_a_master_resume(self, isolated_db):
        async with _client() as client:
            resp = await client.post(
                "/api/v1/prep-cards/generate", json={"category": "technical"}
            )
        assert resp.status_code == 400

    async def test_generate_passes_the_linked_jobs_description(self, isolated_db):
        workspace_id, resume = await _seed_master_resume(isolated_db)
        job = await isolated_db.create_job(content="JD body text", workspace_id=workspace_id)
        application = await isolated_db.create_application(
            job_id=job["job_id"],
            resume_id=resume["resume_id"],
            workspace_id=workspace_id,
        )
        with patch(
            "app.routers.prep_cards.generate_prep_cards",
            new_callable=AsyncMock,
            return_value=[],
        ) as generate:
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/prep-cards/generate",
                    json={
                        "category": "personal",
                        "application_id": application["application_id"],
                    },
                )
        assert resp.status_code == 200
        assert generate.await_args.kwargs["job_description"] == "JD body text"

    async def test_generate_survives_a_deleted_application(self, isolated_db):
        await _seed_master_resume(isolated_db)
        with patch(
            "app.routers.prep_cards.generate_prep_cards",
            new_callable=AsyncMock,
            return_value=[],
        ) as generate:
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/prep-cards/generate",
                    json={"category": "technical", "application_id": "gone"},
                )
        assert resp.status_code == 200
        assert generate.await_args.kwargs["job_description"] is None


class TestAnswerAndCritique:
    async def test_answer_persists_the_generated_back(self, isolated_db):
        await _seed_master_resume(isolated_db)
        answer = PrepCardAnswer(
            answer="A write-ahead log.", explanation="Because…", examples=["One", "Two"]
        )
        with patch(
            "app.routers.prep_cards.answer_prep_card",
            new_callable=AsyncMock,
            return_value=answer,
        ):
            async with _client() as client:
                card = await _create(client)
                resp = await client.post(f"/api/v1/prep-cards/{card['card_id']}/answer")
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["answer"] == "A write-ahead log."
                assert body["explanation"] == "Because…"
                assert body["examples"] == ["One", "Two"]

                stored = await client.get(f"/api/v1/prep-cards/{card['card_id']}")
                assert stored.json()["answer"] == "A write-ahead log."

    async def test_critique_persists_my_answer_and_the_verdict(self, isolated_db):
        await _seed_master_resume(isolated_db)
        critique = PrepCardCritique(
            score=4, strengths=["Clear"], gaps=["Short"], suggested_rewrite="Try this."
        )
        with patch(
            "app.routers.prep_cards.critique_prep_answer",
            new_callable=AsyncMock,
            return_value=critique,
        ):
            async with _client() as client:
                card = await _create(client, category="personal", question="Why us?")
                resp = await client.post(
                    f"/api/v1/prep-cards/{card['card_id']}/critique",
                    json={"my_answer": "Because I like the product."},
                )
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["my_answer"] == "Because I like the product."
                assert body["critique"]["score"] == 4
                assert body["critique"]["suggested_rewrite"] == "Try this."

    async def test_answer_and_critique_require_a_master_resume(self, isolated_db):
        async with _client() as client:
            card = await _create(client)
            answered = await client.post(f"/api/v1/prep-cards/{card['card_id']}/answer")
            assert answered.status_code == 400
            critiqued = await client.post(
                f"/api/v1/prep-cards/{card['card_id']}/critique",
                json={"my_answer": "Something."},
            )
            assert critiqued.status_code == 400
