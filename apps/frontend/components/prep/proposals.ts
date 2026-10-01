import type {
  InterviewPrepData,
  InterviewPrepQuestion,
} from '@/components/common/resume_previewer_context';
import type { PrepCardProposal } from '@/lib/api/prep-cards';

// Kept out of the components so it stays unit-testable (precedent:
// components/tracker/reorder.ts).

function explanationFor(question: InterviewPrepQuestion): string | null {
  const parts: string[] = [];
  if (question.focus_area) parts.push(question.focus_area);
  for (const point of question.suggested_answer_points ?? []) {
    parts.push(`- ${point}`);
  }
  return parts.length > 0 ? parts.join('\n') : null;
}

/**
 * The one piece of card *data* this module authors itself.
 *
 * It is persisted as a card question, not displayed chrome, so it follows the
 * workspace's content language rather than the (English-only) UI bundle.
 */
const SKILL_GAP_QUESTION: Record<string, (skill: string) => string> = {
  en: (skill) => `${skill}: why does it matter for this role, and how would you approach it?`,
  he: (skill) => `${skill}: למה זה חשוב לתפקיד הזה, ואיך הייתם ניגשים לזה?`,
};

/**
 * Map the builder tab's generated prep into deck proposals.
 *
 * `resume_questions` and `project_follow_ups` are questions about the owner's
 * own resume and projects, so they land as `personal`; `skill_gaps` are
 * preparation targets, so they become `technical` questions. `role_fit_analysis`
 * and `talking_points` are not questions and are not imported.
 *
 * Imported proposals carry no answer: `suggested_answer_points` are preparation
 * hints, not a model answer, so the card back still offers "Generate answer".
 */
export function proposalsFromInterviewPrep(
  prep: InterviewPrepData,
  contentLanguage: string
): PrepCardProposal[] {
  const skillGapQuestion = SKILL_GAP_QUESTION[contentLanguage] ?? SKILL_GAP_QUESTION.en;
  const proposals: PrepCardProposal[] = [];

  for (const question of [...(prep.resume_questions ?? []), ...(prep.project_follow_ups ?? [])]) {
    if (!question?.question) continue;
    proposals.push({
      category: 'personal',
      question: question.question,
      explanation: explanationFor(question),
    });
  }

  for (const gap of prep.skill_gaps ?? []) {
    if (!gap?.skill) continue;
    proposals.push({
      category: 'technical',
      question: skillGapQuestion(gap.skill),
      explanation: gap.why_it_matters || null,
    });
  }

  return proposals;
}
