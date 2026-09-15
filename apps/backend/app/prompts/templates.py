"""LLM prompt templates for resume processing."""

# Language code to full name mapping
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
    "pt": "Brazilian Portuguese",
    "fr": "French",
    "ko": "Korean",
}


def get_language_name(code: str) -> str:
    """Get full language name from code."""
    return LANGUAGE_NAMES.get(code, "English")


# A complete v2 document with example values - used for prompts that must show
# the LLM the expected output shape when there is no prior document.
RESUME_SCHEMA_EXAMPLE = """{
  "schemaVersion": 2,
  "header": {
    "name": "John Doe",
    "headline": "Software Engineer",
    "contacts": [
      {"kind": "email", "label": "john@example.com", "value": "john@example.com", "url": ""},
      {"kind": "phone", "label": "+1-555-0100", "value": "+1-555-0100", "url": ""},
      {"kind": "location", "label": "San Francisco, CA", "value": "San Francisco, CA", "url": ""},
      {"kind": "github", "label": "", "value": "github.com/johndoe", "url": "https://github.com/johndoe"}
    ]
  },
  "sections": [
    {
      "key": "summary",
      "heading": "Summary",
      "kind": "text",
      "visible": true,
      "column": "main",
      "text": "Experienced software engineer with 5+ years building distributed systems."
    },
    {
      "key": "experience",
      "heading": "Experience",
      "kind": "entries",
      "visible": true,
      "column": "main",
      "entries": [
        {
          "title": "Senior Software Engineer",
          "subtitle": "Tech Corp",
          "meta": "San Francisco, CA",
          "period": "Jan 2020 - Present",
          "links": [],
          "summary": "Owned the billing platform and led a team of four engineers.",
          "bullets": [
            {"text": "Led development of microservices architecture", "style": "bullet"},
            {"text": "Improved system performance by 40%", "style": "bullet"}
          ]
        }
      ]
    },
    {
      "key": "education",
      "heading": "Education",
      "kind": "entries",
      "visible": true,
      "column": "main",
      "entries": [
        {
          "title": "University of California",
          "subtitle": "B.S. Computer Science",
          "meta": "Berkeley, CA",
          "period": "2014 - 2018",
          "links": [],
          "summary": "Graduated with honors.",
          "bullets": []
        }
      ]
    },
    {
      "key": "projects",
      "heading": "Projects",
      "kind": "entries",
      "visible": true,
      "column": "main",
      "entries": [
        {
          "title": "Open Source Tool",
          "subtitle": "Creator & Maintainer",
          "meta": "",
          "period": "Mar 2021 - Present",
          "links": [{"kind": "github", "url": "https://github.com/johndoe/tool"}],
          "summary": "",
          "bullets": [
            {"text": "Built CLI tool with 1000+ GitHub stars", "style": "bullet"},
            {"text": "Used by 50+ companies worldwide", "style": "bullet"}
          ]
        }
      ]
    },
    {
      "key": "skills",
      "heading": "Skills & Awards",
      "kind": "groups",
      "visible": true,
      "column": "side",
      "groups": [
        {"label": "Technical Skills", "values": ["Python", "JavaScript", "AWS", "Docker"]},
        {"label": "Certifications", "values": ["AWS Solutions Architect"]},
        {"label": "Awards", "values": ["Employee of the Year 2022"]}
      ]
    },
    {
      "key": "languages",
      "heading": "Languages",
      "kind": "tags",
      "visible": true,
      "column": "side",
      "tags": ["English (Native)", "Spanish (Conversational)"]
    },
    {
      "key": "publications",
      "heading": "Publications",
      "kind": "entries",
      "visible": true,
      "column": "main",
      "entries": [
        {
          "title": "Paper Title",
          "subtitle": "Journal Name",
          "meta": "",
          "period": "Jun 2023",
          "links": [],
          "summary": "",
          "bullets": [
            {"text": "Brief description of the publication", "style": "bullet"}
          ]
        }
      ]
    },
    {
      "key": "volunteer_work",
      "heading": "Volunteer Work",
      "kind": "text",
      "visible": true,
      "column": "main",
      "text": "Description of volunteer activities..."
    }
  ]
}"""

# Shape for improve prompts - the header is preserved from the original resume
# and must not be echoed back.
IMPROVE_SCHEMA_EXAMPLE = """{
  "schemaVersion": 2,
  "sections": [
    {
      "id": "copy the section id from the original",
      "key": "summary",
      "heading": "Summary",
      "kind": "text",
      "visible": true,
      "column": "main",
      "text": "Experienced software engineer with 5+ years building distributed systems."
    },
    {
      "id": "copy the section id from the original",
      "key": "experience",
      "heading": "Experience",
      "kind": "entries",
      "visible": true,
      "column": "main",
      "entries": [
        {
          "id": "copy the entry id from the original",
          "title": "Senior Software Engineer",
          "subtitle": "Tech Corp",
          "meta": "San Francisco, CA",
          "period": "Jan 2020 - Present",
          "links": [],
          "summary": "Owned the billing platform and led a team of four engineers.",
          "bullets": [
            {"text": "Led development of microservices architecture", "style": "bullet"},
            {"text": "Improved system performance by 40%", "style": "bullet"}
          ]
        }
      ]
    },
    {
      "id": "copy the section id from the original",
      "key": "skills",
      "heading": "Skills & Awards",
      "kind": "groups",
      "visible": true,
      "column": "side",
      "groups": [
        {"label": "Technical Skills", "values": ["Python", "JavaScript", "AWS", "Docker"]},
        {"label": "Awards", "values": ["Employee of the Year 2022"]}
      ]
    }
  ]
}"""

PARSE_RESUME_PROMPT = """Parse this resume into JSON. Output ONLY the JSON object, no other text.

Example output format:
{schema}

Rules:
- Emit EVERY section the source contains. "sections" is an ordered list and its
  order follows the source document's order.
- Conventional keys, when the source has them: "summary", "experience",
  "education", "projects", "skills". Any OTHER section you find (publications,
  volunteer work, research, certifications, military service, languages,
  hobbies, interests, references...) becomes one more entry in "sections" with a
  snake_case key derived from its own heading. NEVER discard a section and never
  fold it into an unrelated one.
- Choose each section's "kind" from its content: one prose block -> "text";
  dated or titled items -> "entries"; a flat list of short values -> "tags";
  labelled lists of short values -> "groups". A skills block with labels such as
  "Languages & Frameworks" or "Cloud / Data" is "groups", and the labels are
  whatever the source uses - do not rename them.
- "heading" keeps the source's own wording for that section.
- Put an entry's leading paragraph (prose that appears before its bullet rows)
  in "summary" and its bullet rows in "bullets". An entry may have BOTH: never
  drop the paragraph, and never turn it into a bullet.
- Every bullet is an object with "text" and "style". Use "bullet" for a normal
  bullet row and "plain" for a row that should render without a bullet marker
  (for example a subheading or a standalone label).
- Put contact details in "header.contacts", one contact per item, and put the
  candidate's name and professional title in "header.name"/"header.headline".
- Use "" for missing text fields and [] for missing arrays. Leave the content
  fields a section's kind does not use empty.
- Do NOT emit "id" fields; the application assigns identifiers.
- "period" preserves the original date precision verbatim. Keep months when
  present: "Jan 2020 - Dec 2023", "May 2021 - Present". Use "YYYY - YYYY" only
  when the source has no months.
- Normalize date separators: "2020-2021" -> "2020 - 2021", "Current"/"Ongoing"
  -> "Present". Do NOT discard months.
- For ambiguous dates like "3 years experience", infer approximate years from
  context or use "~YYYY"
- Flag overlapping dates (concurrent roles) by preserving both, don't merge
- A "## Links extracted from the PDF file" block is ground truth, not resume
  content. Never copy its lines into any text field. Put each url on the
  matching item: a header link becomes an entry in "header.contacts" with the
  given kind and that url, and an entry link becomes an item in that entry's
  "links" with the given kind.
- A contact whose link had no readable anchor text is icon-only: emit it with
  "label" and "value" empty and only "url" set. Do not invent a label.
- The input may be LaTeX source. Then \\section{{X}} is a section heading,
  \\item is a bullet, \\href{{url}}{{text}} is a link (header contacts for
  header urls, "links" on the entry for entry-row urls), and \\textbf{{x}} /
  \\textit{{x}} inside a bullet become <strong>x</strong> / <em>x</em> —
  bullets are the only field that carries markup. Read unknown macros for
  their argument text and drop the macro itself.

Resume to parse:
{resume_text}"""

EXTRACT_KEYWORDS_PROMPT = """Extract job requirements as JSON. Output ONLY the JSON object, no other text.

Example format:
{{
  "company": "Acme Corp",
  "role": "Senior Backend Engineer",
  "required_skills": ["Python", "AWS"],
  "preferred_skills": ["Kubernetes"],
  "experience_requirements": ["5+ years"],
  "education_requirements": ["Bachelor's in CS"],
  "key_responsibilities": ["Lead team"],
  "keywords": ["microservices", "agile"],
  "experience_years": 5,
  "seniority_level": "senior"
}}

Extract numeric years (e.g., "5+ years" → 5) and infer seniority level.
Set "company" to the hiring company name and "role" to the job title exactly as
written in the posting; use an empty string for either if it is not stated.

Job description:
{job_description}"""

CRITICAL_TRUTHFULNESS_RULES_TEMPLATE = """CRITICAL TRUTHFULNESS RULES - NEVER VIOLATE:
1. DO NOT add any skill, tool, technology, or certification that is not explicitly mentioned in the original resume
2. DO NOT invent numeric achievements (e.g., "increased by 30%") unless they exist in original
3. DO NOT add company names, product names, or technical terms not in the original
4. DO NOT upgrade experience level (e.g., "Junior" -> "Senior")
5. DO NOT add languages, frameworks, or platforms the candidate hasn't used
6. DO NOT extend employment dates or change timelines. Copy date ranges exactly as they appear, including months.
7. {rule_7}
8. Preserve factual accuracy - only use information provided by the candidate
9. NEVER remove existing skills, certifications, languages, or awards. You may reorder by relevance, but every original item must remain.

Violation of these rules could cause serious problems for the candidate in job interviews.
"""


def _build_truthfulness_rules(rule_7: str) -> str:
    return CRITICAL_TRUTHFULNESS_RULES_TEMPLATE.format(rule_7=rule_7)


CRITICAL_TRUTHFULNESS_RULES = {
    "nudge": _build_truthfulness_rules(
        "DO NOT add new bullet points or content - only rephrase existing content"
    ),
    "keywords": _build_truthfulness_rules(
        "You may rephrase existing bullet points to include keywords, but do NOT add new bullet points"
    ),
    "full": _build_truthfulness_rules(
        "You may expand existing bullet points or add new ones that elaborate on existing work, but DO NOT invent entirely new responsibilities"
    ),
}

IMPROVE_RESUME_PROMPT_NUDGE = """Lightly nudge this resume toward the job description. Output ONLY the JSON object, no other text.

{critical_truthfulness_rules}

IMPORTANT: Generate ALL text content (section text, entry summaries, bullets, tags, group values) in {output_language}.
Do NOT include "header" in your output - it will be preserved from the original resume.

Rules:
- Make minimal, conservative edits only where there is a clear existing match
- Do NOT change the candidate's role, industry, or seniority level
- Do NOT introduce new tools, technologies, or certifications not already present
- Do NOT add new bullet points or sections
- Preserve original bullet count and ordering within each section
- Keep every bullet's "style" value ("bullet" or "plain") exactly as in the original
- Keep proper nouns (names, company names, locations) unchanged
- Preserve the document's structure exactly: the same sections in the same order with the same "key", "heading", "kind", "visible" and "column"; the same entry count per section; the same entry "title", "subtitle", "meta" and "period"; and every "id" echoed verbatim. If an entry's "bullets" is [] in the original, keep it []. Do NOT generate bullets for entries that had none.
- Copy every "period" value EXACTLY as it appears in the original resume (including any month prefixes like "Jan 2020 - Present"). Do not shorten, reformat, or drop months.
- If the resume is non-technical, do NOT add technical jargon
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Job Description:
{job_description}

Keywords to emphasize (only if already supported by resume content):
{job_keywords}

Original Resume:
{original_resume}

Output in this JSON format:
{schema}"""

IMPROVE_RESUME_PROMPT_KEYWORDS = """Enhance this resume with relevant keywords from the job description. Output ONLY the JSON object, no other text.

{critical_truthfulness_rules}

IMPORTANT: Generate ALL text content (section text, entry summaries, bullets, tags, group values) in {output_language}.
Do NOT include "header" in your output - it will be preserved from the original resume.

Rules:
- Strengthen alignment by weaving in relevant keywords where evidence already exists
- You may rephrase bullet points to include keyword phrasing
- Do NOT introduce new skills, tools, or certifications not in the resume
- Do NOT change role, industry, or seniority level
- Keep every bullet's "style" value ("bullet" or "plain") exactly as in the original
- Preserve the document's structure exactly: the same sections in the same order with the same "key", "heading", "kind", "visible" and "column"; the same entry count per section; the same entry "title", "subtitle", "meta" and "period"; and every "id" echoed verbatim. If an entry's "bullets" is [] in the original, keep it []. Do NOT generate bullets for entries that had none.
- Copy every "period" value EXACTLY as it appears in the original resume (including any month prefixes like "Jan 2020 - Present"). Do not shorten, reformat, or drop months.
- If resume is non-technical, keep language non-technical while still aligning keywords
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Job Description:
{job_description}

Keywords to emphasize:
{job_keywords}

Original Resume:
{original_resume}

Output in this JSON format:
{schema}"""

IMPROVE_RESUME_PROMPT_FULL = """Tailor this resume for the job. Output ONLY the JSON object, no other text.

{critical_truthfulness_rules}

IMPORTANT: Generate ALL text content (section text, entry summaries, bullets, tags, group values) in {output_language}.
Do NOT include "header" in your output - it will be preserved from the original resume.

Rules:
- Make targeted adjustments to bullet points to align with job description phrasing. Preserve the candidate's original details and voice - adjust wording, do not rewrite entirely.
- DO NOT invent new information
- Preserve existing action verbs. Do not invent quantifiable achievements not in the original.
- Keep proper nouns (names, company names, locations) unchanged
- Translate job titles, descriptions, and skills to {output_language}
- Keep every bullet's "style" value ("bullet" or "plain") exactly as in the original
- Preserve the document's structure exactly: the same sections in the same order with the same "key", "heading", "kind", "visible" and "column"; the same entry count per section; the same entry "title", "subtitle", "meta" and "period"; and every "id" echoed verbatim. If an entry's "bullets" is [] in the original, keep it []. Do NOT generate bullets for entries that had none.
- Improve every section the same way, including sections the candidate created themselves
- Copy every "period" value EXACTLY as it appears in the original resume (including any month prefixes like "Jan 2020 - Present"). Do not shorten, reformat, or drop months.
- Calculate and emphasize total relevant experience duration when it matches requirements
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Job Description:
{job_description}

Keywords to emphasize:
{job_keywords}

Original Resume:
{original_resume}

Output in this JSON format:
{schema}"""

IMPROVE_PROMPT_OPTIONS = [
    {
        "id": "nudge",
        "label": "Light nudge",
        "description": "Minimal edits to better align existing experience.",
    },
    {
        "id": "keywords",
        "label": "Keyword enhance",
        "description": "Blend in relevant keywords without changing role or scope.",
    },
    {
        "id": "full",
        "label": "Full tailor",
        "description": "Comprehensive tailoring using the job description.",
    },
]

IMPROVE_RESUME_PROMPTS = {
    "nudge": IMPROVE_RESUME_PROMPT_NUDGE,
    "keywords": IMPROVE_RESUME_PROMPT_KEYWORDS,
    "full": IMPROVE_RESUME_PROMPT_FULL,
}

DEFAULT_IMPROVE_PROMPT_ID = "keywords"


COVER_LETTER_PROMPT = """Write a brief cover letter for this job application.

IMPORTANT: Write in {output_language}.

Job Description:
{job_description}

Candidate Resume (JSON):
{resume_data}

Requirements:
- 100-150 words maximum
- 3-4 short paragraphs
- Opening: Reference ONE specific thing from the job description (product, tech stack, or problem they're solving) - not generic excitement about "the role"
- Middle: Pick 1-2 qualifications from resume that DIRECTLY match stated requirements, and reframe them in the job's language/terminology where the candidate's proven experience supports it (e.g., if the resume shows "built automated data pipelines" and the job says "ETL," describe that real work as ETL) - prioritize relevance over impressiveness
- Closing: Simple availability to discuss, no desperate enthusiasm
- If resume shows career transition, frame the pivot as intentional and relevant
- Extract company name from job description - do not use placeholders
- Do NOT invent information not in the resume
- Tone: Confident peer, not eager applicant
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Output plain text only. No JSON, no markdown formatting."""

OUTREACH_MESSAGE_PROMPT = """Generate a cold outreach message for LinkedIn or email about this job opportunity.

IMPORTANT: Write in {output_language}.

Job Description:
{job_description}

Candidate Resume (JSON):
{resume_data}

Guidelines:
- 70-100 words maximum (shorter than a cover letter)
- First sentence: Reference specific detail from job description (team, product, technical challenge) - never open with "I'm reaching out" or "I saw your posting"
- One sentence on strongest matching qualification with a concrete metric if available
- End with low-friction ask: "Worth a quick chat?" not "I'd love the opportunity to discuss"
- Tone: How you'd message a former colleague, not a stranger
- Do NOT include placeholder brackets
- Do NOT use phrases like "excited about" or "passionate about"
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Output plain text only. No JSON, no markdown formatting."""

INTERVIEW_PREP_PROMPT = """Generate structured interview preparation for this tailored resume and job.

IMPORTANT: Write in {output_language}.
Do NOT translate JSON property names. Keep every JSON key exactly as shown in the schema; translate only string values.

Job Description:
{job_description}

Candidate Resume (JSON):
{resume_data}

Truthfulness guardrails:
- Use only evidence from the resume JSON and job description.
- Do NOT invent experience, tools, employers, metrics, certifications, skills, responsibilities, education, projects, or claims beyond the provided evidence.
- Do NOT imply the candidate has a skill or background unless it is present in the resume.
- Skill gaps are preparation targets only. They are not claimed candidate skills.
- If a job requirement is not evidenced by the resume, present it as something to prepare for or explain honestly.

Return ONLY a valid JSON object with exactly these top-level keys:
{{
  "role_fit_analysis": ["Short evidence-based role-fit observation"],
  "resume_questions": [
    {{
      "question": "Interview question grounded in the resume and job",
      "focus_area": "Resume evidence or job requirement being tested",
      "suggested_answer_points": ["Truthful point based on resume evidence"]
    }}
  ],
  "project_follow_ups": [
    {{
      "question": "Follow-up question about a real resume project or experience",
      "focus_area": "Project, impact, tradeoff, or implementation detail",
      "suggested_answer_points": ["Truthful point based on resume evidence"]
    }}
  ],
  "skill_gaps": [
    {{
      "skill": "Job-relevant skill or topic to prepare",
      "why_it_matters": "Why this topic may come up for this role",
      "preparation_suggestion": "How to prepare without claiming unsupported experience"
    }}
  ],
  "talking_points": ["Concise role-specific talking point grounded in the resume"]
}}

Content requirements:
- role_fit_analysis: 3-5 bullets.
- resume_questions: 5-8 questions.
- project_follow_ups: 3-6 questions.
- skill_gaps: 3-5 preparation targets.
- talking_points: 5-8 concise points.
- Keep all suggested answer points factual and resume-grounded.
- Do NOT use markdown fences or commentary outside the JSON."""

GENERATE_TITLE_PROMPT = """Extract the job title and company name from this job description.

IMPORTANT: Write in {output_language}.

Job Description:
{job_description}

Rules:
- Format: "Role @ Company" (e.g., "Senior Frontend Engineer @ Stripe")
- If the company name is not found, return just the role (e.g., "Senior Frontend Engineer")
- Maximum 60 characters
- Use the most specific role title mentioned
- Do not add any other text, quotes, or formatting

Output the title only, nothing else."""


# Diff-based improvement: outputs targeted changes instead of full resume

DIFF_STRATEGY_INSTRUCTIONS = {
    "nudge": "Make minimal edits. Only rephrase where there is a clear match. Do not add new bullet points.",
    "keywords": "Weave in relevant keywords where evidence already exists. You may rephrase bullets but do not add new ones.",
    "full": "Make targeted adjustments. You may rephrase bullets, add verified JD skills, and add new bullets that elaborate on existing work, but do not invent new responsibilities.",
}

SKILL_TARGET_PLAN_PROMPT = """Build a concise skill target plan for tailoring this resume to the job.

Return ONLY a JSON object. Do not rewrite the resume.

Rules:
1. Prefer required and preferred JD skills.
2. Include existing resume skills that are highly relevant to the JD.
3. You may include JD skills that are missing from the resume skills list.
4. Do not include skills unrelated to the JD.
5. Do not include certifications.
6. Generate reasons in {output_language}.

Existing resume skills:
{existing_skills}

JD keywords and skills:
{job_keywords}

Job Description:
{job_description}

Resume JSON:
{original_resume}

Output this exact JSON format:
{{
  "target_skills": [
    {{
      "skill": "skill name",
      "reason": "why this skill should be emphasized"
    }}
  ],
  "strategy_notes": "brief notes for the next editing pass"
}}"""

DIFF_IMPROVE_PROMPT = """Given this resume and job description, output a JSON object with targeted changes to better align the resume with the job.

RULES:
1. Only modify content; never change names, companies, dates, institutions, or degrees
2. Do not invent metrics or achievements not supported by the original resume text
3. Do not add new sections and do not add or remove entries; only change content at the paths listed below
4. {strategy_instruction}
5. Each change MUST include the original text (copied exactly) so it can be verified
6. For each change, explain WHY it helps match the job description
7. Generate all new text in {output_language}
8. Do not use em dash characters
9. Keep changes minimal and targeted; do not rewrite content that already aligns well
10. Exception to rule 2: you may add a skill only if it appears in the verified skill targets below
11. By DEFAULT, scan EVERY path listed below - section text, entry summaries, bullets, tags and group values - for content that already demonstrates a job-description keyword or skill, and reframe that text using the job description's terminology where it is not already phrased that way (per rule 9, leave content that already aligns well), while preserving the candidate's actual accomplishment. Do NOT add new work, metrics, or responsibilities; only restate existing content in the JD's language, and verify every reframe stays factually accurate.
12. Preserve original capitalization, especially for proper nouns, technical terms (e.g., REST, API, AWS), and acronyms. Do not change the casing of words that were capitalized in the original.

{editable_paths}

Every path above is a real path in THIS resume: use these section keys verbatim and never invent a path for a section that is not listed. Actions: "replace" (text paths), "append" (add one bullet, path "sections.<key>.entries[i].bullets", only when the strategy allows it), "reorder" (a tags or group values list), "add_skill" (add one verified skill to a tags or group values list).

Keywords to emphasize (only if already supported by resume content):
{job_keywords}

Verified skill targets:
{skill_targets}

Job Description:
{job_description}

Original Resume:
{original_resume}

Output this exact JSON format, nothing else:
{{
  "changes": [
    {{
      "path": "sections.<entries section key>.entries[0].bullets[1].text",
      "action": "replace",
      "original": "the exact original text at this path",
      "value": "the improved text",
      "reason": "why this change helps"
    }},
    {{
      "path": "sections.<text section key>.text",
      "action": "replace",
      "original": "the current summary text",
      "value": "the improved summary",
      "reason": "why this change helps"
    }},
    {{
      "path": "sections.<skills section key>.groups[0].values",
      "action": "reorder",
      "original": null,
      "value": ["most relevant skill first", "then next", "..."],
      "reason": "reordered to prioritize JD-relevant skills"
    }},
    {{
      "path": "sections.<skills section key>.groups[0].values",
      "action": "add_skill",
      "original": null,
      "value": "verified skill target missing from the skills list",
      "reason": "added verified JD skill for review"
    }}
  ],
  "strategy_notes": "brief summary of the tailoring approach"
}}"""
