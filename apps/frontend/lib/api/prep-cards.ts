import { apiFetch, apiPost, apiPatch, apiDelete } from './client';

// `technical` cards are studied as a flip-card game; `personal` cards are
// rehearsed by writing an answer and asking the LLM to critique it.
export type PrepCardCategory = 'technical' | 'personal';

// Manual three-way rating; there is no scheduling algorithm.
export type PrepCardConfidence = 'unrated' | 'again' | 'good' | 'easy';

export interface PrepCardCritique {
  score: number;
  strengths: string[];
  gaps: string[];
  suggested_rewrite: string;
}

export interface PrepCard {
  card_id: string;
  category: PrepCardCategory;
  question: string;
  answer: string | null;
  explanation: string | null;
  examples: string[] | null;
  my_answer: string | null;
  critique: PrepCardCritique | null;
  confidence: PrepCardConfidence;
  source: string;
  application_id: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PrepCardListResponse {
  cards: PrepCard[];
}

export interface PrepCardCreate {
  category: PrepCardCategory;
  question: string;
  answer?: string | null;
  explanation?: string | null;
  examples?: string[] | null;
  application_id?: string | null;
}

export interface PrepCardUpdate {
  category?: PrepCardCategory;
  question?: string;
  answer?: string | null;
  explanation?: string | null;
  examples?: string[] | null;
  my_answer?: string | null;
  confidence?: PrepCardConfidence;
  application_id?: string | null;
}

// A generated question the user has not accepted yet.
export interface PrepCardProposal {
  category: PrepCardCategory;
  question: string;
  explanation: string | null;
}

export interface PrepCardGenerateResponse {
  proposals: PrepCardProposal[];
}

export interface PrepCardActionResponse {
  message: string;
  affected: number;
}

// FastAPI returns `detail` as a string for HTTPException but as an array of
// `{ msg, loc, ... }` objects for validation errors — coerce both to a string
// so error messages never render as "[object Object]".
function extractDetail(data: unknown): string | null {
  if (!data || typeof data !== 'object') return null;
  const detail = (data as { detail?: unknown }).detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) =>
        d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : null
      )
      .filter((m): m is string => Boolean(m));
    if (messages.length > 0) return messages.join('; ');
  }
  // A dict detail (e.g. HTTPException(detail={...})) — stringify so it reads as
  // something rather than "[object Object]".
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    try {
      return JSON.stringify(detail);
    } catch {
      return null;
    }
  }
  return null;
}

async function asJson<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(extractDetail(data) || `${fallback} (status ${res.status}).`);
  }
  return res.json() as Promise<T>;
}

// List the workspace's cards, optionally filtered to one category.
export async function listPrepCards(category?: PrepCardCategory): Promise<PrepCardListResponse> {
  const path = category ? `/prep-cards?category=${category}` : '/prep-cards';
  const res = await apiFetch(path, { credentials: 'include' });
  return asJson<PrepCardListResponse>(res, 'Failed to load cards');
}

// Create one card by hand.
export async function createPrepCard(payload: PrepCardCreate): Promise<PrepCard> {
  const res = await apiPost('/prep-cards', payload);
  return asJson<PrepCard>(res, 'Failed to save card');
}

// Accept a reviewed batch of proposals into the deck.
export async function bulkCreatePrepCards(cards: PrepCardCreate[]): Promise<PrepCardListResponse> {
  const res = await apiPost('/prep-cards/bulk-create', { cards });
  return asJson<PrepCardListResponse>(res, 'Failed to save cards');
}

// Update one card (question/answer/category/confidence/own answer).
export async function updatePrepCard(cardId: string, payload: PrepCardUpdate): Promise<PrepCard> {
  const res = await apiPatch(`/prep-cards/${cardId}`, payload);
  return asJson<PrepCard>(res, 'Failed to save card');
}

// Delete one card.
export async function deletePrepCard(cardId: string): Promise<void> {
  const res = await apiDelete(`/prep-cards/${cardId}`);
  await asJson<PrepCardActionResponse>(res, 'Failed to delete card');
}

// Delete many cards.
export async function bulkDeletePrepCards(cardIds: string[]): Promise<PrepCardActionResponse> {
  const res = await apiPost('/prep-cards/bulk-delete', { card_ids: cardIds });
  return asJson<PrepCardActionResponse>(res, 'Failed to delete cards');
}

// Propose questions from the master resume. Persists nothing.
export async function generatePrepCards(payload: {
  category: PrepCardCategory;
  count?: number;
  application_id?: string | null;
}): Promise<PrepCardGenerateResponse> {
  const res = await apiPost('/prep-cards/generate', payload);
  return asJson<PrepCardGenerateResponse>(res, 'Failed to generate cards');
}

// Author the back of one card (answer, explanation, examples) and store it.
export async function answerPrepCard(cardId: string): Promise<PrepCard> {
  const res = await apiPost(`/prep-cards/${cardId}/answer`, {});
  return asJson<PrepCard>(res, 'Failed to generate an answer');
}

// Store the owner's own answer and have the LLM critique it.
export async function critiquePrepCard(cardId: string, myAnswer: string): Promise<PrepCard> {
  const res = await apiPost(`/prep-cards/${cardId}/critique`, { my_answer: myAnswer });
  return asJson<PrepCard>(res, 'Failed to review the answer');
}
