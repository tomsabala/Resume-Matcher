"""Regression test for the improve/preview -> improve/confirm hash gate.

The bug: ``improve/preview`` hashes the RAW ``improved_data`` dict, while
``improve/confirm`` hashes its schema round-trip
(``request.improved_data.model_dump()``). A document that merely OMITS optional
fields — which ``ResumeDocument`` defaults — therefore hashes differently on the
two sides, so a valid tailoring is rejected with 400 ("preview hash mismatch")
whenever the stored ``processed_data`` is not already schema-complete.
``_hash_improved_data`` must canonicalize through ``ResumeDocument`` so the two
sides agree.
"""

from __future__ import annotations

from typing import Any

from app.routers.resumes import _hash_improved_data
from app.schemas.document import ResumeDocument


def _canonical(data: dict[str, Any]) -> dict[str, Any]:
    return ResumeDocument.model_validate(data).model_dump(mode="json")


def test_hash_is_stable_across_document_roundtrip() -> None:
    # A document whose header omits `contacts`/`headline` and whose entry omits
    # the optional `meta`/`links`/`summary` (and its bullet the default `style`)
    # — exactly the non-canonical stored-processed_data shape that triggers the
    # confirm 400.
    raw: dict[str, Any] = {
        "schemaVersion": 2,
        "header": {"name": "Jane Doe"},
        "sections": [
            {
                "id": "s-projects",
                "key": "projects",
                "heading": "Projects",
                "kind": "entries",
                "entries": [
                    {
                        "id": "e-proj",
                        "title": "Proj",
                        "subtitle": "Author",
                        "period": "2022",
                        "bullets": [{"text": "Built it"}],
                    }
                ],
            }
        ],
    }
    # The raw dict and its schema-complete round-trip differ in key set...
    assert "links" not in raw["sections"][0]["entries"][0]
    assert "links" in _canonical(raw)["sections"][0]["entries"][0]
    # ...but their hashes MUST match, or preview (hashes raw) and confirm
    # (hashes the round-trip) disagree and reject a valid tailoring.
    assert _hash_improved_data(raw) == _hash_improved_data(_canonical(raw))


def test_hash_distinguishes_genuinely_different_resumes() -> None:
    # Anti-theater: canonicalization must NOT collapse real content differences.
    def document(summary: str) -> dict[str, Any]:
        return {
            "schemaVersion": 2,
            "header": {"name": "Jane"},
            "sections": [
                {
                    "id": "s-summary",
                    "key": "summary",
                    "heading": "Summary",
                    "kind": "text",
                    "text": summary,
                }
            ],
        }

    assert _hash_improved_data(document("Backend engineer.")) != _hash_improved_data(
        document("Frontend engineer.")
    )
