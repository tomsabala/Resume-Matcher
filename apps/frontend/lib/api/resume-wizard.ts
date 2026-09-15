import { emptyDocument, type ResumeDocument } from '@/lib/types/document';
import { apiPost } from './client';

/**
 * Where the wizard is in the interview.
 *
 * `intro`, `contact` and `review` are the fixed bookends; everything between
 * them addresses one section of the document under construction by its key, so
 * the wizard covers user-authored sections without a hardcoded list.
 */
export type ResumeWizardSection = 'intro' | 'contact' | 'review' | `section:${string}`;

export type ResumeWizardStep = 'intro' | 'question' | 'review' | 'complete';
export type ResumeWizardAction = 'start' | 'answer' | 'skip' | 'back' | 'review';

export interface ResumeWizardQuestion {
  text: string;
  section: ResumeWizardSection;
}

export interface ResumeWizardProgress {
  current: number;
  total: number;
}

export interface ResumeWizardHistoryEntry {
  question: string;
  answer: string;
  section: ResumeWizardSection;
  resume_data_before: ResumeDocument;
}

export interface ResumeWizardState {
  step: ResumeWizardStep;
  resume_data: ResumeDocument;
  current_question: ResumeWizardQuestion;
  history: ResumeWizardHistoryEntry[];
  asked_count: number;
  inferred_skills: string[];
  is_complete: boolean;
  progress: ResumeWizardProgress;
  warnings: string[];
}

export interface ResumeWizardTurnRequest {
  state: ResumeWizardState;
  action: ResumeWizardAction;
  answer?: { text: string };
}

export interface ResumeWizardTurnResponse {
  state: ResumeWizardState;
}

export interface ResumeWizardFinalizeResponse {
  message: string;
  request_id: string;
  resume_id: string;
  processing_status: 'ready';
  is_master: boolean;
}

export const INTRO_QUESTION =
  "Hi — I'll help you build your master resume. What's your name, and what kind of role are you going for?";

export function createInitialResumeWizardState(): ResumeWizardState {
  return {
    step: 'intro',
    resume_data: emptyDocument(),
    current_question: { text: INTRO_QUESTION, section: 'intro' },
    history: [],
    asked_count: 0,
    inferred_skills: [],
    is_complete: false,
    progress: { current: 0, total: 8 },
    warnings: [],
  };
}

export async function postResumeWizardTurn(
  payload: ResumeWizardTurnRequest
): Promise<ResumeWizardTurnResponse> {
  const response = await apiPost('/resume-wizard/turn', payload);
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(text || `Resume wizard turn failed with status ${response.status}`);
  }
  return response.json();
}

export async function finalizeResumeWizard(
  state: ResumeWizardState
): Promise<ResumeWizardFinalizeResponse> {
  const response = await apiPost('/resume-wizard/finalize', { state });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(text || `Resume wizard finalize failed with status ${response.status}`);
  }
  return response.json();
}
