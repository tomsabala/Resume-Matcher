import { apiFetch, apiDelete } from './client';

/**
 * Recent AI failures.
 *
 * The backend keeps a short, bounded tail of failed AI operations so the
 * dashboard can say *why* something failed — an exhausted output budget reads
 * very differently from a rejected API key. The records carry no prompt,
 * resume or model output.
 */
export type AIFailureKind = 'truncated' | 'malformed' | 'empty' | 'invalid' | 'provider';

export interface AIFailure {
  id: string;
  /** ISO-8601 UTC. */
  at: string;
  /** The schema the call was producing: `resume`, `diff`, `keywords`, … */
  operation: string;
  kind: AIFailureKind;
  detail: string;
  model?: string | null;
  provider?: string | null;
  attempts?: number | null;
  max_tokens?: number | null;
}

interface AIFailureListResponse {
  failures: AIFailure[];
  dismissed: number;
}

export async function fetchAIFailures(): Promise<AIFailure[]> {
  const res = await apiFetch('/diagnostics/ai-failures');
  if (!res.ok) {
    throw new Error(`Failed to load AI diagnostics (status ${res.status}).`);
  }
  const payload = (await res.json()) as AIFailureListResponse;
  return payload.failures ?? [];
}

/** Drop the tracked failures; returns how many were dismissed. */
export async function dismissAIFailures(): Promise<number> {
  const res = await apiDelete('/diagnostics/ai-failures');
  if (!res.ok) {
    throw new Error(`Failed to dismiss AI diagnostics (status ${res.status}).`);
  }
  const payload = (await res.json()) as AIFailureListResponse;
  return payload.dismissed ?? 0;
}
