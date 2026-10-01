"""Content-language detection — which language a generated artifact speaks.

The workspace setting is only the fallback: get this wrong and a Hebrew prep
card is answered in English, or an English resume is rewritten in Hebrew.
"""

import pytest

from app.services.language import (
    contains_script,
    detect_content_language,
    output_language_for,
)

pytestmark = pytest.mark.unit

HEBREW_PROSE = "מהנדס תוכנה עם שש שנות ניסיון בפיתוח מערכות צד שרת"
ENGLISH_PROSE = "Software engineer with six years building server-side systems."


def test_hebrew_prose_is_hebrew() -> None:
    assert detect_content_language(HEBREW_PROSE) == "he"


def test_english_prose_is_english() -> None:
    assert detect_content_language(ENGLISH_PROSE) == "en"


def test_a_hebrew_bullet_dense_with_latin_is_still_hebrew() -> None:
    """The ratio exists for this: real Hebrew resumes name Latin tools."""
    bullet = "הובלתי מעבר ל-React ושיפרתי את זמן הטעינה ב-30%"
    assert detect_content_language([bullet, bullet]) == "he"


def test_english_schema_keys_do_not_outvote_hebrew_values() -> None:
    document = {"workExperience": [{"schemaVersion": 2, "summary": HEBREW_PROSE}]}
    assert detect_content_language(document) == "he"


@pytest.mark.parametrize("sample", ["Tom", {}, "", [], {"heading": "N/A"}])
def test_too_few_letters_to_judge(sample: object) -> None:
    assert detect_content_language(sample) is None


def test_the_first_decidable_sample_wins() -> None:
    assert detect_content_language("Tom", HEBREW_PROSE, ENGLISH_PROSE) == "he"


def test_an_undecidable_sample_falls_back_to_the_workspace() -> None:
    assert output_language_for("", default="he") == "Hebrew"
    assert output_language_for(HEBREW_PROSE, default="en") == "Hebrew"
    assert output_language_for(ENGLISH_PROSE, default="he") == "English"


def test_contains_script_and_detection_differ_on_purpose() -> None:
    """One Hebrew word breaks the LaTeX preamble; it does not make the
    document Hebrew."""
    mixed = "Led the React migration and shipped it worldwide שלום"
    assert contains_script(mixed, "he") is True
    assert detect_content_language(mixed) == "en"


def test_contains_script_walks_nested_content() -> None:
    document = {"sections": [{"items": ["English bullet", "שלום"]}]}
    assert contains_script(document, "he") is True
    assert contains_script({"sections": [{"items": ["English bullet"]}]}, "he") is False


def test_an_unknown_script_is_never_contained() -> None:
    assert contains_script(HEBREW_PROSE, "fr") is False
