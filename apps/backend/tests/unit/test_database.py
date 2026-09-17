"""Tests for the real SQLAlchemy/SQLite layer (app.database.Database).

Every integration test mocks `db`, so the actual persistence layer was barely
exercised. These run a real SQLite database against a temp file, so CRUD,
master-resume assignment, the jobs ``metadata_json`` round-trip, applications,
and stats are verified end-to-end on the storage.
"""

import pytest

from app.database import Database


@pytest.fixture
async def db(tmp_path):
    database = Database(db_path=tmp_path / "test_db.db")
    yield database
    await database.close()


@pytest.fixture
async def workspace(db):
    return await db.default_workspace_id()


@pytest.fixture
async def cards(db, workspace):
    """Two ``{job_id, resume_id}`` pairs that exist in ``workspace``.

    ``create_application`` validates both ids against the caller's scope, so a
    tracker test needs real rows.
    """
    pairs = []
    for i in (1, 2):
        job = await db.create_job(content=f"jd{i}", workspace_id=workspace)
        resume = await db.create_resume(content=f"r{i}", workspace_id=workspace)
        pairs.append({"job_id": job["job_id"], "resume_id": resume["resume_id"]})
    return pairs


class TestResumeCrud:
    async def test_create_and_get(self, db, workspace):
        created = await db.create_resume(
            content="# Resume", filename="r.pdf", workspace_id=workspace
        )
        assert created["resume_id"]
        fetched = await db.get_resume(created["resume_id"], workspace_id=workspace)
        assert fetched is not None
        assert fetched["content"] == "# Resume"
        assert fetched["filename"] == "r.pdf"

    async def test_get_missing_returns_none(self, db, workspace):
        assert await db.get_resume("does-not-exist", workspace_id=workspace) is None

    async def test_list_resumes(self, db, workspace):
        await db.create_resume(content="a", workspace_id=workspace)
        await db.create_resume(content="b", workspace_id=workspace)
        assert len(await db.list_resumes(workspace)) == 2

    async def test_update_resume_changes_field_and_timestamp(self, db, workspace):
        created = await db.create_resume(content="x", workspace_id=workspace)
        updated = await db.update_resume(
            created["resume_id"], {"title": "New Title"}, workspace_id=workspace
        )
        assert updated["title"] == "New Title"
        assert updated["updated_at"] >= created["updated_at"]

    async def test_update_missing_raises(self, db, workspace):
        with pytest.raises(ValueError):
            await db.update_resume("missing", {"title": "X"}, workspace_id=workspace)

    async def test_delete_resume(self, db, workspace):
        created = await db.create_resume(content="x", workspace_id=workspace)
        assert await db.delete_resume(created["resume_id"], workspace_id=workspace) is True
        assert await db.get_resume(created["resume_id"], workspace_id=workspace) is None

    async def test_delete_missing_returns_false(self, db, workspace):
        assert await db.delete_resume("missing", workspace_id=workspace) is False

    async def test_original_markdown_absence_semantics(self, db, workspace):
        # Omitted when None (preserve TinyDB behavior); present when supplied.
        without = await db.create_resume(content="x", workspace_id=workspace)
        assert "original_markdown" not in without
        with_md = await db.create_resume(
            content="x", original_markdown="# raw", workspace_id=workspace
        )
        fetched = await db.get_resume(with_md["resume_id"], workspace_id=workspace)
        assert fetched["original_markdown"] == "# raw"

    async def test_interview_prep_round_trips_as_text(self, db, workspace):
        created = await db.create_resume(
            content="x",
            interview_prep='{"role_fit_analysis":["fit"]}',
            workspace_id=workspace,
        )
        fetched = await db.get_resume(created["resume_id"], workspace_id=workspace)
        assert fetched["interview_prep"] == '{"role_fit_analysis":["fit"]}'


class TestMasterResume:
    async def test_no_master_initially(self, db, workspace):
        assert await db.get_master_resume(workspace) is None

    async def test_set_master_unsets_previous(self, db, workspace):
        r1 = await db.create_resume(content="1", workspace_id=workspace)
        r2 = await db.create_resume(content="2", workspace_id=workspace)

        assert await db.set_master_resume(r1["resume_id"], workspace_id=workspace) is True
        assert (await db.get_master_resume(workspace))["resume_id"] == r1["resume_id"]

        assert await db.set_master_resume(r2["resume_id"], workspace_id=workspace) is True
        master = await db.get_master_resume(workspace)
        assert master["resume_id"] == r2["resume_id"]
        # Only one master at a time.
        assert sum(1 for r in await db.list_resumes(workspace) if r["is_master"]) == 1

    async def test_set_master_missing_returns_false(self, db, workspace):
        assert await db.set_master_resume("missing", workspace_id=workspace) is False

    async def test_atomic_first_upload_becomes_master(self, db, workspace):
        created = await db.create_resume_atomic_master(
            content="first", processing_status="ready", workspace_id=workspace
        )
        assert created["is_master"] is True

    async def test_atomic_second_upload_not_master(self, db, workspace):
        await db.create_resume_atomic_master(
            content="first", processing_status="ready", workspace_id=workspace
        )
        second = await db.create_resume_atomic_master(
            content="second", processing_status="ready", workspace_id=workspace
        )
        assert second["is_master"] is False

    async def test_atomic_recovers_when_master_stuck(self, db, workspace):
        # Master stuck in "failed" → next upload is promoted to master.
        first = await db.create_resume_atomic_master(
            content="first", processing_status="failed", workspace_id=workspace
        )
        assert first["is_master"] is True
        second = await db.create_resume_atomic_master(
            content="second", processing_status="ready", workspace_id=workspace
        )
        assert second["is_master"] is True
        assert (await db.get_master_resume(workspace))["resume_id"] == second["resume_id"]


class TestJobs:
    async def test_create_and_get_job(self, db, workspace):
        created = await db.create_job(
            content="Engineer role", resume_id="r1", workspace_id=workspace
        )
        fetched = await db.get_job(created["job_id"], workspace_id=workspace)
        assert fetched["content"] == "Engineer role"
        assert fetched["resume_id"] == "r1"

    async def test_get_missing_job_returns_none(self, db, workspace):
        assert await db.get_job("missing", workspace_id=workspace) is None

    async def test_update_job(self, db, workspace):
        created = await db.create_job(content="old", workspace_id=workspace)
        updated = await db.update_job(
            created["job_id"], {"content": "new"}, workspace_id=workspace
        )
        assert updated["content"] == "new"

    async def test_update_missing_job_returns_none(self, db, workspace):
        assert (
            await db.update_job("missing", {"content": "x"}, workspace_id=workspace)
            is None
        )

    async def test_dynamic_fields_round_trip_as_top_level(self, db, workspace):
        """Dynamic pipeline fields must survive write→read as top-level keys.

        This is the highest-risk migration detail: ``/improve/confirm`` rejects
        with 400 if ``preview_hash``/``preview_hashes`` don't round-trip.
        """
        created = await db.create_job(content="jd", workspace_id=workspace)
        await db.update_job(
            created["job_id"],
            {
                "job_keywords": {"required_skills": ["Python", "AWS"]},
                "job_keywords_hash": "deadbeef",
                "preview_hash": "abc123",
                "preview_hashes": {"keywords": "abc123", "nudge": "def456"},
                "preview_prompt_id": "keywords",
                "company": "Acme Corp",
                "role": "Staff Engineer",
            },
            workspace_id=workspace,
        )
        fetched = await db.get_job(created["job_id"], workspace_id=workspace)
        # Core fields preserved.
        assert fetched["content"] == "jd"
        # Dynamic fields flattened to the top level.
        assert fetched["preview_hash"] == "abc123"
        assert fetched["preview_hashes"] == {"keywords": "abc123", "nudge": "def456"}
        assert fetched["job_keywords_hash"] == "deadbeef"
        assert fetched["job_keywords"]["required_skills"] == ["Python", "AWS"]
        assert fetched["company"] == "Acme Corp"
        assert fetched["role"] == "Staff Engineer"

    async def test_update_job_merges_metadata(self, db, workspace):
        created = await db.create_job(content="jd", workspace_id=workspace)
        await db.update_job(
            created["job_id"], {"preview_hash": "h1"}, workspace_id=workspace
        )
        await db.update_job(
            created["job_id"], {"company": "Acme"}, workspace_id=workspace
        )
        fetched = await db.get_job(created["job_id"], workspace_id=workspace)
        # The second update must not wipe the first dynamic field.
        assert fetched["preview_hash"] == "h1"
        assert fetched["company"] == "Acme"


class TestImprovements:
    async def test_create_and_lookup_by_tailored_resume(self, db, workspace):
        await db.create_improvement(
            original_resume_id="orig",
            tailored_resume_id="tailored-1",
            job_id="job-1",
            improvements=[{"path": "summary"}],
            workspace_id=workspace,
        )
        found = await db.get_improvement_by_tailored_resume(
            "tailored-1", workspace_id=workspace
        )
        assert found is not None
        assert found["job_id"] == "job-1"

    async def test_lookup_missing_returns_none(self, db, workspace):
        assert (
            await db.get_improvement_by_tailored_resume("nope", workspace_id=workspace)
            is None
        )


class TestApplications:
    async def test_create_defaults_and_position(self, db, workspace, cards):
        a = await db.create_application(**cards[0], workspace_id=workspace)
        assert a["status"] == "applied"
        assert a["position"] == 0
        assert a["applied_at"] is not None  # applied → stamped
        b = await db.create_application(**cards[1], workspace_id=workspace)
        assert b["position"] == 1  # appended to the column

    async def test_saved_status_has_no_applied_at(self, db, workspace, cards):
        a = await db.create_application(
            **cards[0], status="saved", workspace_id=workspace
        )
        assert a["applied_at"] is None

    async def test_create_dedupes_on_job_and_resume(self, db, workspace, cards):
        a = await db.create_application(**cards[0], workspace_id=workspace)
        again = await db.create_application(**cards[0], workspace_id=workspace)
        assert again["application_id"] == a["application_id"]
        assert len(await db.list_applications(workspace_id=workspace)) == 1

    async def test_move_renumbers_columns(self, db, workspace, cards):
        a = await db.create_application(**cards[0], workspace_id=workspace)
        b = await db.create_application(**cards[1], workspace_id=workspace)
        # Move a to the front of "interview".
        moved = await db.update_application(
            a["application_id"],
            {"status": "interview", "position": 0},
            workspace_id=workspace,
        )
        assert moved["status"] == "interview"
        assert moved["position"] == 0
        # The "applied" column renumbered: b is now position 0.
        applied = await db.list_applications(status="applied", workspace_id=workspace)
        assert [x["application_id"] for x in applied] == [b["application_id"]]
        assert applied[0]["position"] == 0

    async def test_bulk_update_and_delete(self, db, workspace, cards):
        a = await db.create_application(**cards[0], workspace_id=workspace)
        b = await db.create_application(**cards[1], workspace_id=workspace)
        moved = await db.bulk_update_applications(
            [a["application_id"], b["application_id"]],
            "rejected",
            workspace_id=workspace,
        )
        assert moved == 2
        rejected = await db.list_applications(status="rejected", workspace_id=workspace)
        assert {x["position"] for x in rejected} == {0, 1}
        deleted = await db.bulk_delete_applications(
            [a["application_id"]], workspace_id=workspace
        )
        assert deleted == 1
        remaining = await db.list_applications(status="rejected", workspace_id=workspace)
        assert len(remaining) == 1
        assert remaining[0]["position"] == 0  # renumbered after delete


class TestApiKeyStore:
    async def test_set_get_delete_ciphertext(self, db, workspace):
        db.set_api_key_ciphertext(workspace, "openai", "ct-openai")
        db.set_api_key_ciphertext(workspace, "anthropic", "ct-anthropic")
        assert db.get_api_key_ciphertexts(workspace) == {
            "openai": "ct-openai",
            "anthropic": "ct-anthropic",
        }
        db.delete_api_key(workspace, "openai")
        assert db.get_api_key_ciphertexts(workspace) == {"anthropic": "ct-anthropic"}
        db.clear_api_keys(workspace)
        assert db.get_api_key_ciphertexts(workspace) == {}

    async def test_same_provider_isolated_per_workspace(self, db, workspace):
        other = (await db.create_workspace(name="Other"))["workspace_id"]
        db.set_api_key_ciphertext(workspace, "openai", "ct-first")
        db.set_api_key_ciphertext(other, "openai", "ct-second")
        assert db.get_api_key_ciphertexts(workspace) == {"openai": "ct-first"}
        assert db.get_api_key_ciphertexts(other) == {"openai": "ct-second"}
        db.delete_api_key(workspace, "openai")
        assert db.get_api_key_ciphertexts(workspace) == {}
        assert db.get_api_key_ciphertexts(other) == {"openai": "ct-second"}


class TestStatsAndReset:
    async def test_get_stats(self, db, workspace):
        await db.create_resume(content="a", workspace_id=workspace)
        await db.set_master_resume(
            (await db.list_resumes(workspace))[0]["resume_id"], workspace_id=workspace
        )
        await db.create_job(content="jd", workspace_id=workspace)
        stats = await db.get_stats(workspace)
        assert stats["total_resumes"] == 1
        assert stats["total_jobs"] == 1
        assert stats["has_master_resume"] is True

    async def test_reset_workspace_truncates(self, db, workspace, cards):
        await db.create_application(**cards[0], workspace_id=workspace)
        db.set_api_key_ciphertext(workspace, "openai", "ct-openai")
        await db.reset_workspace(workspace)
        stats = await db.get_stats(workspace)
        assert stats["total_resumes"] == 0
        assert stats["total_jobs"] == 0
        assert stats["has_master_resume"] is False
        # Applications are cleared too (no orphans after a full reset).
        assert await db.list_applications(workspace_id=workspace) == []
        # Stored credentials deliberately survive a reset.
        assert db.get_api_key_ciphertexts(workspace) == {"openai": "ct-openai"}
