import { describe, expect, it } from 'vitest';
import { proposalsFromInterviewPrep } from '@/components/prep/proposals';
import type { InterviewPrepData } from '@/components/common/resume_previewer_context';

/**
 * The import mapping is the product rule for "Send to deck": questions about the
 * owner become personal cards, skill gaps become technical ones, and the two
 * non-question sections are not cards at all.
 */

const PREP: InterviewPrepData = {
  role_fit_analysis: ['Strong Python background.'],
  resume_questions: [
    {
      question: 'Tell me about the Acme migration.',
      focus_area: 'Migration experience',
      suggested_answer_points: ['Led the cutover', 'Zero downtime'],
    },
  ],
  project_follow_ups: [
    {
      question: 'How did you test the parser?',
      focus_area: 'Testing',
      suggested_answer_points: ['Property-based tests'],
    },
  ],
  skill_gaps: [
    {
      skill: 'Kubernetes',
      why_it_matters: 'The role runs on GKE.',
      preparation_suggestion: 'Read the docs.',
    },
  ],
  talking_points: ['Loves distributed systems.'],
};

describe('proposalsFromInterviewPrep', () => {
  it('maps resume questions and project follow-ups to personal cards', () => {
    const personal = proposalsFromInterviewPrep(PREP).filter((p) => p.category === 'personal');
    expect(personal.map((p) => p.question)).toEqual([
      'Tell me about the Acme migration.',
      'How did you test the parser?',
    ]);
  });

  it('builds a technical question from each skill gap', () => {
    const technical = proposalsFromInterviewPrep(PREP).filter((p) => p.category === 'technical');
    expect(technical).toEqual([
      {
        category: 'technical',
        question: 'Kubernetes: why does it matter for this role, and how would you approach it?',
        explanation: 'The role runs on GKE.',
      },
    ]);
  });

  it('carries the focus area and answer points into the explanation', () => {
    const [first] = proposalsFromInterviewPrep(PREP);
    expect(first.explanation).toBe('Migration experience\n- Led the cutover\n- Zero downtime');
  });

  it('imports nothing from role fit analysis or talking points', () => {
    const proposals = proposalsFromInterviewPrep({
      ...PREP,
      resume_questions: [],
      project_follow_ups: [],
      skill_gaps: [],
    });
    expect(proposals).toEqual([]);
  });
});
