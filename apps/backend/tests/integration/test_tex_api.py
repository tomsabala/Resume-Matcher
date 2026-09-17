"""LaTeX source and PDF endpoints.

The invariants that matter: the override wins once saved, clearing it goes
back to generation, and a host with no engine degrades to a ``.tex`` download
instead of a 500.
"""

import copy
import io
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader

from app.latex.compile import LatexCompileError, LatexUnavailableError, latex_engine
from app.main import app
from app.schemas.document import ResumeDocument
from tests.integration.test_dynamic_sections_api import owner_document

pytestmark = pytest.mark.integration


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
    )
    return created["resume_id"]


async def test_the_generated_source_is_compilable_latex_not_a_stub(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        response = await client.get(f"/api/v1/resumes/{resume_id}/tex")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_override"] is False
    source = body["source"]
    assert source.startswith("\\documentclass")
    assert source.rstrip().endswith("\\end{document}")
    # The user's own content reached the output.
    assert sample_resume["header"]["name"] in source


async def test_user_content_is_escaped_on_the_way_into_the_source(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """A resume is untrusted input; it must not become LaTeX control flow."""
    document = copy.deepcopy(sample_resume)
    document["header"]["name"] = "Ada & 100% \\input{/etc/passwd}"
    resume_id = await _seed(isolated_db, document)

    async with _client() as client:
        source = (await client.get(f"/api/v1/resumes/{resume_id}/tex")).json()["source"]

    assert r"\input{/etc/passwd}" not in source
    assert r"Ada \& 100\% \textbackslash{}input\{/etc/passwd\}" in source


async def test_an_unknown_template_is_rejected_with_the_valid_choices(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        response = await client.get(
            f"/api/v1/resumes/{resume_id}/tex", params={"template": "nope"}
        )

    assert response.status_code == 400
    assert "tex-classic" in response.json()["detail"]


async def test_a_saved_override_wins_until_it_is_cleared(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    resume_id = await _seed(isolated_db, sample_resume)
    mine = "\\documentclass{article}\\begin{document}mine\\end{document}"

    async with _client() as client:
        saved = await client.put(
            f"/api/v1/resumes/{resume_id}/tex", json={"source": mine}
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["is_override"] is True

        served = (await client.get(f"/api/v1/resumes/{resume_id}/tex")).json()
        assert served["source"] == mine
        assert served["is_override"] is True

        # ...and the document is still reachable behind it.
        regenerated = (
            await client.get(
                f"/api/v1/resumes/{resume_id}/tex", params={"regenerate": True}
            )
        ).json()
        assert regenerated["source"] != mine
        assert regenerated["is_override"] is False

        cleared = await client.delete(f"/api/v1/resumes/{resume_id}/tex")
        assert cleared.status_code == 200
        assert cleared.json()["is_override"] is False

        after = (await client.get(f"/api/v1/resumes/{resume_id}/tex")).json()
        assert after["source"] != mine
        assert after["is_override"] is False


async def test_an_empty_override_is_refused_rather_than_stored(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """An empty override would read as "no override" and silently vanish."""
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        response = await client.put(
            f"/api/v1/resumes/{resume_id}/tex", json={"source": ""}
        )

    assert response.status_code == 422


async def test_the_source_download_serves_a_tex_attachment(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        response = await client.get(f"/api/v1/resumes/{resume_id}/tex/source")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-tex")
    assert ".tex" in response.headers["content-disposition"]
    assert response.text.startswith("\\documentclass")


async def test_a_host_without_an_engine_answers_503_not_500(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """The deployment story: no TeX in the image is a degraded capability,
    and the UI needs a distinguishable status to offer the .tex instead."""
    resume_id = await _seed(isolated_db, sample_resume)

    with patch(
        "app.routers.tex.compile_tex_to_pdf",
        side_effect=LatexUnavailableError("no engine"),
    ):
        async with _client() as client:
            response = await client.get(f"/api/v1/resumes/{resume_id}/tex/pdf")

    assert response.status_code == 503

    # The source route is unaffected, so the fallback actually exists.
    async with _client() as client:
        assert (
            await client.get(f"/api/v1/resumes/{resume_id}/tex/source")
        ).status_code == 200


async def test_a_broken_override_returns_the_engine_log_not_a_generic_500(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """The user wrote the LaTeX; without the log they cannot fix it."""
    resume_id = await _seed(isolated_db, sample_resume)

    with patch(
        "app.routers.tex.compile_tex_to_pdf",
        side_effect=LatexCompileError(message="LaTeX compilation failed.", log="! Undefined control sequence."),
    ):
        async with _client() as client:
            response = await client.get(f"/api/v1/resumes/{resume_id}/tex/pdf")

    assert response.status_code == 422
    assert "Undefined control sequence" in response.json()["detail"]["log"]


async def test_capabilities_reports_the_templates_the_ui_may_offer() -> None:
    async with _client() as client:
        response = await client.get("/api/v1/resumes/tex/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["templates"] == ["tex-classic", "tex-compact"]
    assert body["can_compile"] is (body["engine"] is not None)


async def test_a_user_created_section_reaches_the_latex(isolated_db: Any) -> None:
    """Phase 1's promise holds through LaTeX: sections are data, not code."""
    document = owner_document()
    document["sections"].append(
        {
            "id": "s-military",
            "key": "military_service",
            "heading": "Military Service",
            "headingI18nKey": None,
            "kind": "entries",
            "visible": True,
            "column": "main",
            "text": "",
            "entries": [
                {
                    "id": "e-idf",
                    "title": "Combat Officer",
                    "subtitle": "",
                    "meta": "",
                    "period": "2016 -- 2020",
                    "links": [],
                    "summary": "",
                    "bullets": [{"text": "Paratroopers Brigade", "style": "bullet"}],
                }
            ],
            "tags": [],
            "groups": [],
        }
    )
    created = await isolated_db.create_resume(
        content="{}",
        content_type="document",
        processed_data=document,
        processing_status="ready",
    )

    async with _client() as client:
        source = (
            await client.get(f"/api/v1/resumes/{created['resume_id']}/tex")
        ).json()["source"]

    assert r"\section{Military Service}" in source
    assert "Paratroopers Brigade" in source


async def test_an_unknown_resume_is_404_on_every_route() -> None:
    async with _client() as client:
        for path in ("/tex", "/tex/source", "/tex/pdf"):
            assert (
                await client.get(f"/api/v1/resumes/does-not-exist{path}")
            ).status_code == 404


async def test_a_tex_edit_lands_on_the_version_timeline(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """The document is unchanged by a source edit, so plain content dedup
    would drop the checkpoint and the edit could never be restored."""
    resume_id = await _seed(isolated_db, sample_resume)
    mine = "\\documentclass{article}\\begin{document}mine\\end{document}"

    async with _client() as client:
        before = (await client.get(f"/api/v1/resumes/{resume_id}/versions")).json()
        await client.put(f"/api/v1/resumes/{resume_id}/tex", json={"source": mine})
        after = (await client.get(f"/api/v1/resumes/{resume_id}/versions")).json()

    assert len(after["versions"]) == len(before["versions"]) + 1
    head = after["versions"][0]
    assert head["origin"] == "tex_edit"
    assert head["tex_source_mode"] == "edited"

    async with _client() as client:
        detail = (
            await client.get(f"/api/v1/versions/{head['version_id']}")
        ).json()
    assert detail["tex_source"] == mine


async def test_saving_the_same_source_twice_does_not_stack_versions(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    resume_id = await _seed(isolated_db, sample_resume)
    mine = "\\documentclass{article}\\begin{document}mine\\end{document}"

    async with _client() as client:
        await client.put(f"/api/v1/resumes/{resume_id}/tex", json={"source": mine})
        once = (await client.get(f"/api/v1/resumes/{resume_id}/versions")).json()
        await client.put(f"/api/v1/resumes/{resume_id}/tex", json={"source": mine})
        twice = (await client.get(f"/api/v1/resumes/{resume_id}/versions")).json()

    assert len(twice["versions"]) == len(once["versions"])


async def test_a_document_save_carries_the_override_forward_in_history(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """A later content save must not erase the override from the timeline —
    restoring that version would silently lose the user's LaTeX."""
    resume_id = await _seed(isolated_db, sample_resume)
    mine = "\\documentclass{article}\\begin{document}mine\\end{document}"
    edited = copy.deepcopy(
        ResumeDocument.model_validate(sample_resume).model_dump(mode="json")
    )
    edited["header"]["headline"] = "Changed headline"

    async with _client() as client:
        await client.put(f"/api/v1/resumes/{resume_id}/tex", json={"source": mine})
        patched = await client.patch(f"/api/v1/resumes/{resume_id}", json=edited)
        assert patched.status_code == 200, patched.text
        versions = (await client.get(f"/api/v1/resumes/{resume_id}/versions")).json()
        head = (
            await client.get(f"/api/v1/versions/{versions['versions'][0]['version_id']}")
        ).json()

    assert head["origin"] == "manual"
    assert head["tex_source"] == mine
    assert head["tex_source_mode"] == "edited"


async def test_restoring_a_pre_override_version_brings_back_its_source(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """A checkpoint is a document *and* its LaTeX; restoring half of it would
    hand back a pair that never existed."""
    resume_id = await _seed(isolated_db, sample_resume)
    mine = "\\documentclass{article}\\begin{document}mine\\end{document}"

    document = ResumeDocument.model_validate(sample_resume).model_dump(mode="json")
    async with _client() as client:
        # A checkpoint from before the override existed.
        assert (
            await client.patch(f"/api/v1/resumes/{resume_id}", json=document)
        ).status_code == 200
        versions = (await client.get(f"/api/v1/resumes/{resume_id}/versions")).json()
        clean_version_id = versions["versions"][0]["version_id"]

        await client.put(f"/api/v1/resumes/{resume_id}/tex", json={"source": mine})
        assert (await client.get(f"/api/v1/resumes/{resume_id}/tex")).json()[
            "is_override"
        ] is True

        restored = await client.post(
            f"/api/v1/resumes/{resume_id}/restore",
            json={"version_id": clean_version_id},
        )
        assert restored.status_code == 200, restored.text

        after = (await client.get(f"/api/v1/resumes/{resume_id}/tex")).json()

    assert after["is_override"] is False
    assert after["source"] != mine


async def test_the_picker_page_size_reaches_the_generated_source(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """Page size is a class option, so without it the preamble hardcodes A4
    and the picker's US Letter does nothing."""
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        a4 = await client.get(f"/api/v1/resumes/{resume_id}/tex")
        letter = await client.get(
            f"/api/v1/resumes/{resume_id}/tex", params={"pageSize": "LETTER"}
        )

    assert "a4paper" in a4.json()["source"]
    assert "letterpaper" in letter.json()["source"]
    assert "a4paper" not in letter.json()["source"]


async def test_the_formatting_controls_reach_the_generated_source(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """Margins, base font size and spacing are panel controls; if the route
    drops them the preview and the export keep the reference look whatever the
    sliders say."""
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        response = await client.get(
            f"/api/v1/resumes/{resume_id}/tex",
            params={
                "marginLeft": 20,
                "fontSize": 5,
                "sectionSpacing": 9,
                "bulletLeadIn": 1,
            },
        )

    source = response.json()["source"]
    assert "left=20mm" in source
    assert "12pt]{article}" in source
    # The loosest of the nine section levels: 2.5 x the reference rhythm, so
    # the trailing pull-up is all but gone.
    assert "\\vspace{\\dimexpr -0.5pt + 0.383\\baselineskip\\relax}" in source
    # The tightest lead-in cancels `\parskip` outright.
    assert "\\setlength{\\resumeBulletLead}{0pt}" in source
    assert "scale=0.9" not in source


@pytest.mark.parametrize(("knob", "level"), [("fontSize", 9), ("sectionSpacing", 10)])
async def test_an_out_of_range_formatting_level_is_rejected(
    isolated_db: Any, sample_resume: dict[str, Any], knob: str, level: int
) -> None:
    """The levels are a vocabulary shared with the Chromium route — 1-9 on the
    spacing axes, 1-5 on the font axes. A pt value here used to be a silently
    different meaning of ``fontSize``."""
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        response = await client.get(
            f"/api/v1/resumes/{resume_id}/tex", params={knob: level}
        )

    assert response.status_code == 422


@pytest.mark.skipif(latex_engine() is None, reason="no LaTeX engine installed")
async def test_a_us_letter_compile_produces_a_us_letter_page(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        response = await client.get(
            f"/api/v1/resumes/{resume_id}/tex/pdf", params={"pageSize": "LETTER"}
        )

    assert response.status_code == 200, response.text
    page = PdfReader(io.BytesIO(response.content)).pages[0]
    assert (round(float(page.mediabox.width)), round(float(page.mediabox.height))) == (
        612,
        792,
    )


async def test_the_chromium_route_refuses_a_latex_template(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    """It used to accept any template string and silently render swiss-single,
    which is how a LaTeX selection produced a browser-rendered PDF."""
    resume_id = await _seed(isolated_db, sample_resume)

    async with _client() as client:
        response = await client.get(
            f"/api/v1/resumes/{resume_id}/pdf", params={"template": "tex-classic"}
        )

    assert response.status_code == 400
    assert "/tex/pdf" in response.json()["detail"]
