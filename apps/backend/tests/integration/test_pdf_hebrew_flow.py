"""A Hebrew resume rasterises as glyphs, right-to-left, through real Chromium.

The sibling multilingual test proves embedded glyphs for CJK; this one proves
them for Hebrew *and* adds the thing Hebrew alone needs — that a `dir="rtl"`
document still keeps its Latin runs (tech names, URLs, percentages) in logical
order, which is what per-field `dir="auto"` isolation buys.
"""

import io
from pathlib import Path

import pytest
from pdfminer.high_level import extract_text
from pdfminer.pdfpage import PDFPage
from playwright.async_api import async_playwright

from app.pdf import _launch_browser
from tests.integration.test_pdf_multilingual_flow import _embedded_glyph_characters

HEBREW_SUMMARY = "מהנדס תוכנה עם שבע שנות ניסיון בפיתוח מערכות"
HEBREW_HEADING = "ניסיון מקצועי"
MIXED_BULLET = "הובלתי מעבר ל־React ושיפרתי את זמן הטעינה ב־30%"


async def test_a_hebrew_resume_embeds_glyphs_and_keeps_its_latin_runs(
    tmp_path: Path,
) -> None:
    style_root = (
        Path(__file__).resolve().parents[4] / "apps/frontend/components/resume/styles"
    )
    styles = "\n".join(
        line
        for name in ("_tokens.css", "_base.module.css", "section-kinds.module.css")
        for line in (style_root / name).read_text().splitlines()
        if not line.startswith("@import")
    )
    async with async_playwright() as playwright:
        try:
            browser = await _launch_browser(playwright)
        except Exception as error:
            if "executable" in str(error).lower() or "installation was found" in str(
                error
            ):
                pytest.skip(f"Chromium unavailable: {error}")
            raise
        try:
            page = await browser.new_page()
            await page.set_content(
                f"""
                <style>
                * {{box-sizing: border-box;}}
                html, body {{margin: 0;}}
                {styles}
                .resume-body {{--section-gap: 16px; --margin-top:0; --margin-right:0; --margin-bottom:0; --margin-left:0;}}
                </style>
                <main class="resume-print resume-body" lang="he" dir="rtl">
                  <h1 dir="auto">תום לוי</h1>
                  <h3 dir="auto">{HEBREW_HEADING}</h3>
                  <p dir="auto" id="summary">{HEBREW_SUMMARY}</p>
                  <ul class="bullets">
                    <li class="bulletRow">
                      <span class="marker">&bull;&nbsp;</span>
                      <span dir="auto" id="bullet">{MIXED_BULLET}</span>
                    </li>
                  </ul>
                  <div id="entry-row" style="display: flex; justify-content: space-between; width: 400px">
                    <h4 id="entry-title" dir="auto">מהנדס תוכנה</h4>
                    <span id="date" class="resume-date">2021 - 2024</span>
                  </div>
                </main>
            """,
                wait_until="load",
            )
            await page.emulate_media(media="print")

            # The document direction reaches the rendered nodes, and the bullet
            # marker therefore sits on the right.
            assert (
                await page.evaluate(
                    "() => getComputedStyle(document.querySelector('#summary')).direction"
                )
                == "rtl"
            )
            marker_is_rightmost = await page.evaluate(
                """() => {
                    const row = document.querySelector('.bulletRow');
                    const marker = row.querySelector('.marker');
                    const text = row.querySelector('#bullet');
                    return marker.getBoundingClientRect().left
                        > text.getBoundingClientRect().left;
                }"""
            )
            assert marker_is_rightmost, "RTL bullet marker did not move to the right"

            # The entry row is `justify-between`, so in an RTL document the title
            # starts at the right and the date ends up on the left.
            date_precedes_title = await page.evaluate(
                """() => {
                    const title = document.querySelector('#entry-title');
                    const date = document.querySelector('#date');
                    return date.getBoundingClientRect().left
                        < title.getBoundingClientRect().left;
                }"""
            )
            assert date_precedes_title, "RTL entry row did not mirror its date column"

            pdf = await page.pdf(
                format="A4",
                print_background=True,
                margin={side: "15mm" for side in ("top", "right", "bottom", "left")},
            )
            (tmp_path / "hebrew.pdf").write_bytes(pdf)
            assert len(list(PDFPage.get_pages(io.BytesIO(pdf)))) >= 1

            required_glyphs = set(HEBREW_HEADING.replace(" ", ""))
            assert required_glyphs <= _embedded_glyph_characters(pdf), (
                "Hebrew text has no embedded glyphs; "
                "install Hebrew fonts such as fonts-noto-core"
            )

            compact = "".join(extract_text(io.BytesIO(pdf)).split())
            # The Latin run inside an RTL paragraph must survive intact and in
            # order — the bug per-field isolation exists to prevent.
            assert "React" in compact
            assert "30%" in compact
            # NB: no assertion on the date's *extracted* order — pdfminer has no
            # bidi layer and reports an RTL line visually, which says nothing
            # about the render. The date's alignment is checked in the DOM above.
        finally:
            await browser.close()
