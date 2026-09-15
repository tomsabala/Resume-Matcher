"""Regenerate endpoints: dispatch, partial failure and stable-id targeting."""

import copy
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.routers import enrichment as enrichment_router
from app.schemas.enrichment import (
    RegenerateItemInput,
    RegeneratedItem,
    RegenerateRequest,
)


def _entry(
    entry_id: str, title: str, subtitle: str, bullets: list[str]
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "title": title,
        "subtitle": subtitle,
        "meta": "",
        "period": "",
        "links": [],
        "summary": "",
        "bullets": [{"text": text, "style": "bullet"} for text in bullets],
    }


def _document(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A v2 document with one ENTRIES, one GROUPS and one TAGS section."""
    if entries is None:
        entries = [
            _entry("e-google", "Senior Software Engineer", "Google", ["Old bullet"]),
            _entry("e-acme", "Software Engineer", "Acme", ["Keep me"]),
        ]
    return {
        "schemaVersion": 2,
        "header": {"name": "Jane Doe", "headline": "", "contacts": []},
        "sections": [
            {
                "id": "s-experience",
                "key": "experience",
                "heading": "Experience",
                "kind": "entries",
                "entries": entries,
            },
            {
                "id": "s-skills",
                "key": "skills",
                "heading": "Skills",
                "kind": "groups",
                "groups": [{"label": "Technical Skills", "values": ["Python"]}],
            },
            {
                "id": "s-interests",
                "key": "interests",
                "heading": "Interests",
                "kind": "tags",
                "tags": ["Chess"],
            },
        ],
    }


def _section(document: dict[str, Any], key: str) -> dict[str, Any]:
    return next(section for section in document["sections"] if section["key"] == key)


def _bullet_texts(document: dict[str, Any], key: str, entry_id: str) -> list[str]:
    entry = next(
        row for row in _section(document, key)["entries"] if row["id"] == entry_id
    )
    return [bullet["text"] for bullet in entry["bullets"]]


class TestRegenerateSchemas(unittest.TestCase):
    def test_regenerate_request_instruction_max_length(self) -> None:
        item = RegenerateItemInput(
            item_id="skills:#group:0",
            item_type="values",
            title="Technical Skills",
            current_content=["Python"],
        )

        RegenerateRequest(
            resume_id="resume_1",
            items=[item],
            instruction="x" * 2000,
            output_language="en",
        )

        with self.assertRaises(ValidationError):
            RegenerateRequest(
                resume_id="resume_1",
                items=[item],
                instruction="x" * 2001,
                output_language="en",
            )


class TestRegenerateEndpoints(unittest.IsolatedAsyncioTestCase):
    async def test_regenerate_processes_multiple_items_in_parallel(self) -> None:
        request = RegenerateRequest(
            resume_id="resume_1",
            items=[
                RegenerateItemInput(
                    item_id="experience:e-google",
                    item_type="entry",
                    title="Senior Software Engineer",
                    subtitle="Google",
                    current_content=["Old bullet"],
                ),
                RegenerateItemInput(
                    item_id="skills:#group:0",
                    item_type="values",
                    title="Technical Skills",
                    current_content=["Python"],
                ),
            ],
            instruction="Improve wording",
            output_language="en",
        )

        mock_db = AsyncMock()
        mock_db.get_resume.return_value = {"processed_data": _document()}

        entry_item = RegeneratedItem(
            item_id="experience:e-google",
            item_type="entry",
            title="Senior Software Engineer",
            subtitle="Google",
            original_content=["Old bullet"],
            new_content=["New bullet"],
            diff_summary="Summary",
        )
        values_item = RegeneratedItem(
            item_id="skills:#group:0",
            item_type="values",
            title="Technical Skills",
            original_content=["Python"],
            new_content=["Python", "TypeScript"],
            diff_summary="Summary",
        )

        with (
            patch.object(enrichment_router, "db", mock_db),
            patch.object(
                enrichment_router,
                "_regenerate_experience_or_project",
                AsyncMock(return_value=entry_item),
            ) as mock_regenerate_item,
            patch.object(
                enrichment_router,
                "_regenerate_skills",
                AsyncMock(return_value=values_item),
            ) as mock_regenerate_skills,
        ):
            response = await enrichment_router.regenerate_items(request)

        self.assertEqual(
            [item.item_id for item in response.regenerated_items],
            ["experience:e-google", "skills:#group:0"],
        )
        mock_regenerate_item.assert_awaited()
        mock_regenerate_skills.assert_awaited()

    async def test_regenerate_allows_partial_success_with_errors(self) -> None:
        request = RegenerateRequest(
            resume_id="resume_1",
            items=[
                RegenerateItemInput(
                    item_id="experience:e-google",
                    item_type="entry",
                    title="Senior Software Engineer",
                    subtitle="Google",
                    current_content=["Old bullet"],
                ),
                RegenerateItemInput(
                    item_id="skills:#group:0",
                    item_type="values",
                    title="Technical Skills",
                    current_content=["Python"],
                ),
            ],
            instruction="Improve wording",
            output_language="en",
        )

        mock_db = AsyncMock()
        mock_db.get_resume.return_value = {"processed_data": _document()}

        values_item = RegeneratedItem(
            item_id="skills:#group:0",
            item_type="values",
            title="Technical Skills",
            original_content=["Python"],
            new_content=["Python", "TypeScript"],
            diff_summary="Summary",
        )

        with (
            patch.object(enrichment_router, "db", mock_db),
            patch.object(
                enrichment_router,
                "_regenerate_experience_or_project",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch.object(
                enrichment_router,
                "_regenerate_skills",
                AsyncMock(return_value=values_item),
            ),
        ):
            response = await enrichment_router.regenerate_items(request)

        self.assertEqual(
            [item.item_id for item in response.regenerated_items], ["skills:#group:0"]
        )
        self.assertEqual(
            [err.item_id for err in response.errors], ["experience:e-google"]
        )

    async def test_regenerated_entry_still_applies_after_a_reorder(self) -> None:
        """The reviewed entry is edited even when the list order changed.

        Item ids are stable for the entry's life. Under the old positional
        ``exp_0`` scheme a reorder between regenerate and apply silently
        retargeted whichever entry now sat at that index.
        """
        resume_id = "resume_1"
        stored = _document()

        mock_db = AsyncMock()
        mock_db.get_resume.return_value = {"processed_data": stored}
        mock_db.commit_resume_version.return_value = {}

        request = RegenerateRequest(
            resume_id=resume_id,
            items=[
                RegenerateItemInput(
                    item_id="experience:e-google",
                    item_type="entry",
                    title="Senior Software Engineer",
                    subtitle="Google",
                    current_content=["Old bullet"],
                )
            ],
            instruction="Quantify the impact",
            output_language="en",
        )

        with (
            patch.object(enrichment_router, "db", mock_db),
            patch.object(
                enrichment_router,
                "complete_json",
                AsyncMock(return_value={"new_bullets": ["Rewritten bullet"]}),
            ),
        ):
            regenerated = await enrichment_router.regenerate_items(request)

            # The user reorders the resume before accepting the proposal.
            reordered = copy.deepcopy(stored)
            _section(reordered, "experience")["entries"].reverse()
            mock_db.get_resume.return_value = {"processed_data": reordered}

            result = await enrichment_router.apply_regenerated_items(
                resume_id, regenerated.regenerated_items
            )

        self.assertEqual(result["updated_items"], 1)
        updated = mock_db.commit_resume_version.call_args.args[1]
        # Order is the user's; the edit lands on the reviewed entry regardless.
        self.assertEqual(
            [entry["id"] for entry in _section(updated, "experience")["entries"]],
            ["e-acme", "e-google"],
        )
        self.assertEqual(
            _bullet_texts(updated, "experience", "e-google"), ["Rewritten bullet"]
        )
        self.assertEqual(_bullet_texts(updated, "experience", "e-acme"), ["Keep me"])

    async def test_apply_regenerated_distinguishes_identical_looking_entries(
        self,
    ) -> None:
        resume_id = "resume_1"
        stored = _document(
            [
                _entry("e-first", "Engineer", "Google", ["Bullet A"]),
                _entry("e-second", "Engineer", "Google", ["Bullet B"]),
            ]
        )

        mock_db = AsyncMock()
        mock_db.get_resume.return_value = {"processed_data": stored}
        mock_db.commit_resume_version.return_value = {}

        regenerated_items = [
            RegeneratedItem(
                item_id="experience:e-second",
                item_type="entry",
                title="Engineer",
                subtitle="Google",
                original_content=["Bullet B"],
                new_content=["Bullet B (rewritten)"],
                diff_summary="Summary",
            )
        ]

        with patch.object(enrichment_router, "db", mock_db):
            result = await enrichment_router.apply_regenerated_items(
                resume_id, regenerated_items
            )

        self.assertEqual(result["updated_items"], 1)
        updated = mock_db.commit_resume_version.call_args.args[1]
        self.assertEqual(
            _bullet_texts(updated, "experience", "e-first"), ["Bullet A"]
        )
        self.assertEqual(
            _bullet_texts(updated, "experience", "e-second"),
            ["Bullet B (rewritten)"],
        )

    async def test_apply_regenerated_refuses_when_content_drifted(self) -> None:
        resume_id = "resume_1"

        mock_db = AsyncMock()
        mock_db.get_resume.return_value = {"processed_data": _document()}

        regenerated_items = [
            RegeneratedItem(
                item_id="experience:e-google",
                item_type="entry",
                title="Senior Software Engineer",
                subtitle="Google",
                original_content=["Content the user never reviewed"],
                new_content=["New"],
                diff_summary="Summary",
            )
        ]

        with patch.object(enrichment_router, "db", mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await enrichment_router.apply_regenerated_items(
                    resume_id, regenerated_items
                )

        self.assertEqual(ctx.exception.status_code, 409)
        mock_db.commit_resume_version.assert_not_called()

    async def test_apply_regenerated_updates_tag_and_group_value_lists(self) -> None:
        resume_id = "resume_1"

        mock_db = AsyncMock()
        mock_db.get_resume.return_value = {"processed_data": _document()}
        mock_db.commit_resume_version.return_value = {}

        regenerated_items = [
            RegeneratedItem(
                item_id="skills:#group:0",
                item_type="values",
                title="Technical Skills",
                original_content=["Python"],
                new_content=["Python", "TypeScript"],
                diff_summary="Summary",
            ),
            RegeneratedItem(
                item_id="interests:#tags",
                item_type="values",
                title="Interests",
                original_content=["Chess"],
                new_content=["Chess", "Cycling"],
                diff_summary="Summary",
            ),
        ]

        with patch.object(enrichment_router, "db", mock_db):
            result = await enrichment_router.apply_regenerated_items(
                resume_id, regenerated_items
            )

        self.assertEqual(result["updated_items"], 2)
        updated = mock_db.commit_resume_version.call_args.args[1]
        self.assertEqual(
            _section(updated, "skills")["groups"][0]["values"],
            ["Python", "TypeScript"],
        )
        self.assertEqual(
            _section(updated, "interests")["tags"], ["Chess", "Cycling"]
        )

    async def test_apply_regenerated_refuses_an_unresolvable_item_id(self) -> None:
        resume_id = "resume_1"

        mock_db = AsyncMock()
        mock_db.get_resume.return_value = {"processed_data": _document()}

        regenerated_items = [
            RegeneratedItem(
                item_id="skills:#group:7",
                item_type="values",
                title="Technical Skills",
                original_content=["Python"],
                new_content=["Python", "TypeScript"],
                diff_summary="Summary",
            )
        ]

        with patch.object(enrichment_router, "db", mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await enrichment_router.apply_regenerated_items(
                    resume_id, regenerated_items
                )

        self.assertEqual(ctx.exception.status_code, 409)
        mock_db.commit_resume_version.assert_not_called()
