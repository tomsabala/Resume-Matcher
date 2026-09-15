"""Content guards on the AI prompts.

Four invariants this locks:
1. The prompts describe the v2 document contract and nothing from the deleted
   six-section schema.
2. Every AI path names the REAL paths/sections of the document it is given, so a
   user-created section is first-class AI-editable content.
3. JD-keyword incorporation is the DEFAULT across sections (the maintainer goal).
4. The anti-fabrication clauses stay present. Deterministic final-output
   preservation handles structural loss and unsupported metrics, while weakly
   grounded narrative is held for explicit review. These prompt clauses remain
   the model-facing first layer and should not regress.
"""

from app.prompts import enrichment as enrichment_prompts
from app.prompts import refinement as refinement_prompts
from app.prompts import resume_wizard as wizard_prompts
from app.prompts import templates as template_prompts
from app.prompts.enrichment import ANALYZE_RESUME_PROMPT
from app.prompts.refinement import KEYWORD_INJECTION_PROMPT
from app.prompts.schema import describe_document_schema, describe_editable_paths
from app.prompts.templates import (
    COVER_LETTER_PROMPT,
    DIFF_IMPROVE_PROMPT,
    INTERVIEW_PREP_PROMPT,
    PARSE_RESUME_PROMPT,
    RESUME_SCHEMA_EXAMPLE,
)
from app.schemas.document import (
    Bullet,
    Entry,
    ResumeDocument,
    Section,
    SectionKind,
    TagGroup,
)


def _document() -> ResumeDocument:
    """A document with one section of every kind, including a user-made one."""
    return ResumeDocument(
        header={"name": "Priya Sharma", "headline": "Engineer"},
        sections=[
            Section(
                key="summary", heading="Summary", kind=SectionKind.TEXT, text="Engineer."
            ),
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
            ),
            Section(
                key="languages",
                heading="Languages",
                kind=SectionKind.TAGS,
                tags=["Hindi", "English"],
            ),
            Section(
                key="skills",
                heading="Skills & Awards",
                kind=SectionKind.GROUPS,
                groups=[TagGroup(label="Technical Skills", values=["Python"])],
            ),
        ],
    )


class TestEditablePaths:
    def test_every_section_kind_gets_its_own_paths(self):
        paths = describe_editable_paths(_document())
        assert "sections.summary.text" in paths
        # The acceptance case: a user-created entries section is editable.
        assert "sections.military_service.entries[i].bullets[j].text" in paths
        assert "sections.military_service.entries[i].summary" in paths
        assert "sections.languages.tags" in paths
        assert "sections.skills.groups[i].values" in paths

    def test_paths_never_include_a_section_the_document_lacks(self):
        paths = describe_editable_paths(_document())
        assert "sections.experience" not in paths
        assert "sections.projects" not in paths

    def test_identity_fields_and_header_are_declared_off_limits(self):
        paths = describe_editable_paths(_document())
        assert "OFF LIMITS" in paths
        assert "header" in paths
        for field in ("title", "subtitle", "meta", "period", "links"):
            assert f'"{field}"' in paths

    def test_empty_document_still_states_the_limits(self):
        paths = describe_editable_paths(ResumeDocument())
        assert "OFF LIMITS" in paths
        assert '"sections.' not in paths


class TestDocumentSchemaDescription:
    def test_without_a_document_it_describes_the_shape_and_an_example(self):
        described = describe_document_schema(None)
        assert "EXAMPLE DOCUMENT" in described
        assert RESUME_SCHEMA_EXAMPLE in described
        for kind in ("text", "entries", "tags", "groups"):
            assert kind in described

    def test_the_example_shows_the_shapes_v1_could_not_represent(self):
        # A groups section with arbitrary labels, and an entry carrying BOTH a
        # summary paragraph and bullets. Losing either regresses the parser to
        # "bullets only" / "flat skills".
        assert '"kind": "groups"' in RESUME_SCHEMA_EXAMPLE
        assert '"label": "Certifications"' in RESUME_SCHEMA_EXAMPLE
        assert '"summary": "Owned the billing platform' in RESUME_SCHEMA_EXAMPLE
        assert '"bullets": [' in RESUME_SCHEMA_EXAMPLE

    def test_with_a_document_it_enumerates_the_real_sections(self):
        described = describe_document_schema(_document())
        assert 'key "military_service" | heading "Military Service" | kind entries' in described
        assert 'key "skills" | heading "Skills & Awards" | kind groups' in described
        # The concrete example would compete with the real document.
        assert "EXAMPLE DOCUMENT" not in described


class TestPromptsNameTheRealTargets:
    def test_diff_prompt_interpolates_this_documents_paths(self):
        prompt = DIFF_IMPROVE_PROMPT.format(
            strategy_instruction="Make minimal edits.",
            output_language="English",
            job_keywords="Python",
            skill_targets="Python",
            job_description="A job",
            original_resume="{}",
            editable_paths=describe_editable_paths(_document()),
        )
        assert "sections.military_service.entries[i].bullets[j].text" in prompt
        assert "PATHS you can target" in prompt
        assert "OFF LIMITS" in prompt

    def test_keyword_injection_interpolates_this_documents_sections(self):
        prompt = KEYWORD_INJECTION_PROMPT.format(
            document_schema=describe_document_schema(_document()),
            keywords_to_inject="Python",
            current_resume="{}",
            master_resume="{}",
            job_description="A job",
        )
        assert 'key "military_service"' in prompt
        assert "EVERY section" in prompt
        assert "DEFAULT" in prompt

    def test_parse_prompt_keeps_every_section_it_finds(self):
        prompt = PARSE_RESUME_PROMPT.format(
            schema=describe_document_schema(None), resume_text="Some resume"
        )
        assert "Emit EVERY section" in prompt
        assert "NEVER discard a section" in prompt
        # The model must choose a kind rather than drop unknown sections.
        assert "military service" in prompt
        assert 'Choose each section\'s "kind"' in prompt

    def test_analyze_prompt_makes_the_model_copy_document_ids(self):
        prompt = ANALYZE_RESUME_PROMPT.format(
            resume_json="{}", output_language="English"
        )
        assert "NEVER INVENT THEM" in prompt
        assert '"item_type" is "entry"' in prompt
        assert ":#tags" in prompt
        assert ":#group:" in prompt
        assert "every entry of every" in prompt

    def test_wizard_prompt_is_driven_by_the_documents_sections(self):
        prompt = wizard_prompts.RESUME_WIZARD_TURN_PROMPT.format(
            output_language="English",
            current_target='the section with key "military_service"',
            document_schema=describe_document_schema(_document()),
            section_tokens="intro, contact, review, section:military_service",
            resume_json="{}",
            answer_text="I served in the Signal Corps",
        )
        assert "section:military_service" in prompt
        assert 'To add a new one, omit "id"' in prompt


class TestNoV1VocabularyLeft:
    # The deleted six-section schema must not survive in any prompt string.
    FORBIDDEN = (
        "workExperience",
        "personalProjects",
        "customSections",
        "sectionMeta",
        "descriptionStyles",
        "personalInfo",
        "technicalSkills",
    )

    def test_prompt_modules_only_speak_the_v2_contract(self):
        modules = (
            template_prompts,
            refinement_prompts,
            enrichment_prompts,
            wizard_prompts,
        )
        for module in modules:
            for name, value in vars(module).items():
                if name.startswith("_") or not name.isupper():
                    continue
                texts: list[str] = []
                if isinstance(value, str):
                    texts = [value]
                elif isinstance(value, dict):
                    texts = [v for v in value.values() if isinstance(v, str)]
                for text in texts:
                    for token in self.FORBIDDEN:
                        assert token not in text, f"{module.__name__}.{name}: {token}"


class TestJdIncorporationIsDefault:
    def test_diff_prompt_reframes_by_default(self):
        assert "By DEFAULT" in DIFF_IMPROVE_PROMPT
        assert "reframe" in DIFF_IMPROVE_PROMPT.lower()

    def test_keyword_injection_targets_every_section_by_default(self):
        assert "EVERY section" in KEYWORD_INJECTION_PROMPT
        assert "DEFAULT" in KEYWORD_INJECTION_PROMPT

    def test_cover_letter_reframes_in_jd_terminology(self):
        assert "terminology" in COVER_LETTER_PROMPT.lower()


class TestAntiFabricationClausesPresent:
    def test_diff_prompt_keeps_no_invented_work_clauses(self):
        # rule 11's reframe permission must ship WITH its anti-fabrication clause
        assert "Do NOT add new work, metrics, or responsibilities" in DIFF_IMPROVE_PROMPT
        # rule 2 must remain
        assert "Do not invent metrics or achievements not supported by the original resume" in DIFF_IMPROVE_PROMPT

    def test_keyword_injection_keeps_no_invent_clauses(self):
        assert "do not invent new content, metrics, or work history" in KEYWORD_INJECTION_PROMPT
        assert "Do NOT add skills, technologies, or certifications not in the master resume" in KEYWORD_INJECTION_PROMPT

    def test_cover_letter_keeps_no_invent_clauses(self):
        assert "Do NOT invent information not in the resume" in COVER_LETTER_PROMPT
        assert "proven experience supports it" in COVER_LETTER_PROMPT

    def test_interview_prep_keeps_no_fabrication_guardrails(self):
        assert "Do NOT invent experience" in INTERVIEW_PREP_PROMPT
        assert "tools, employers, metrics, certifications, skills" in INTERVIEW_PREP_PROMPT
        assert "Skill gaps are preparation targets only" in INTERVIEW_PREP_PROMPT
        assert "Do NOT translate JSON property names" in INTERVIEW_PREP_PROMPT
        assert "role_fit_analysis" in INTERVIEW_PREP_PROMPT
        assert "talking_points" in INTERVIEW_PREP_PROMPT

    def test_wizard_prompt_keeps_truthfulness_rules(self):
        prompt = wizard_prompts.RESUME_WIZARD_TURN_PROMPT
        assert "Never invent employers, job titles, dates" in prompt
        assert "Do not add facts they did not give" in prompt
