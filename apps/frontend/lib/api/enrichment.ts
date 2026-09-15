/**
 * API functions for AI-powered resume enrichment.
 */

import { apiFetch, apiPost } from './client';
import type { DiffRow } from './diff';

// Types matching backend schemas (apps/backend/app/schemas/enrichment.py).
//
// `item_id` addresses content by stable id, never by position:
//   entry      -> `<section.key>:<entry.id>`
//   value list -> `<section.key>:#tags` | `<section.key>:#group:<index>`
// `item_type` says what the content *is*; which section holds it is the
// user's choice, so section names are never a category.
export type EnrichmentItemType = 'entry' | 'values';

export interface EnrichmentItem {
  item_id: string;
  item_type: EnrichmentItemType;
  /** The owning section's heading — what the user called it. */
  section_heading?: string;
  title: string;
  subtitle?: string;
  current_description: string[];
  weakness_reason: string;
}

export interface EnrichmentQuestion {
  question_id: string;
  item_id: string;
  question: string;
  placeholder: string;
}

export interface AnalysisResponse {
  items_to_enrich: EnrichmentItem[];
  questions: EnrichmentQuestion[];
  analysis_summary?: string;
}

export interface AnswerInput {
  question_id: string;
  answer: string;
}

export interface EnhancedDescription {
  item_id: string;
  item_type: EnrichmentItemType;
  section_heading?: string;
  title: string;
  original_description: string[];
  enhanced_description: string[];
}

export interface EnhancementItemError {
  item_id: string;
  item_type: EnrichmentItemType;
  section_heading?: string;
  title: string;
  subtitle?: string | null;
  message: string;
}

export interface EnhancementPreview {
  enhancements: EnhancedDescription[];
  errors?: EnhancementItemError[];
}

/**
 * Analyze a resume to identify items that need enrichment.
 * Returns items with weak descriptions and clarifying questions.
 */
export async function analyzeResume(resumeId: string): Promise<AnalysisResponse> {
  const res = await apiFetch(`/enrichment/analyze/${resumeId}`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to analyze resume (status ${res.status}).`);
  }

  return res.json();
}

/**
 * Generate enhanced descriptions from user answers.
 */
export async function generateEnhancements(
  resumeId: string,
  answers: AnswerInput[]
): Promise<EnhancementPreview> {
  const res = await apiPost('/enrichment/enhance', {
    resume_id: resumeId,
    answers,
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to generate enhancements (status ${res.status}).`);
  }

  return res.json();
}

/**
 * Apply enhancements to the master resume.
 */
export async function applyEnhancements(
  resumeId: string,
  enhancements: EnhancedDescription[]
): Promise<{ message: string; updated_items: number }> {
  const res = await apiPost(`/enrichment/apply/${resumeId}`, {
    enhancements,
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to apply enhancements (status ${res.status}).`);
  }

  return res.json();
}

// ============================================
// AI Regenerate Feature Types
// ============================================

export interface RegenerateItemInput {
  item_id: string;
  item_type: EnrichmentItemType;
  title: string;
  subtitle?: string;
  current_content: string[];
}

export interface RegenerateRequest {
  resume_id: string;
  items: RegenerateItemInput[];
  instruction: string;
  output_language?: string;
}

export interface RegeneratedItem {
  item_id: string;
  item_type: EnrichmentItemType;
  title: string;
  subtitle?: string;
  original_content: string[];
  new_content: string[];
  /**
   * Server-computed comparison of `original_content` against `new_content`,
   * word-level spans included — the rows the shared diff surface renders.
   * Paths are `<item_id>[<line>]`.
   */
  rows: DiffRow[];
  diff_summary: string;
}

export interface RegenerateItemError {
  item_id: string;
  item_type: EnrichmentItemType;
  title: string;
  subtitle?: string;
  message: string;
}

export interface RegenerateResponse {
  regenerated_items: RegeneratedItem[];
  errors?: RegenerateItemError[];
}

/**
 * Regenerate selected resume items based on user feedback.
 * Uses AI to rewrite content addressing user's concerns.
 */
export async function regenerateItems(request: RegenerateRequest): Promise<RegenerateResponse> {
  const res = await apiPost('/enrichment/regenerate', request);

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to regenerate content (status ${res.status}).`);
  }

  return res.json();
}

/**
 * Apply regenerated items to the master resume.
 */
export async function applyRegeneratedItems(
  resumeId: string,
  regeneratedItems: RegeneratedItem[]
): Promise<{ message: string; updated_items: number }> {
  const res = await apiPost(`/enrichment/apply-regenerated/${resumeId}`, regeneratedItems);

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Failed to apply changes (status ${res.status}).`);
  }

  return res.json();
}
