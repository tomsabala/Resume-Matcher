/**
 * Resume version history API.
 *
 * History is append-only: a restore writes the chosen version forward as a new
 * head rather than rewinding, so the restore is itself on the timeline.
 */

import { apiFetch, apiPost, apiPatch, apiDelete } from './client';
import type { ResumeDocument } from '@/lib/types/document';

/** What produced a version. Only `manual` saves coalesce. */
export type VersionOrigin =
  'import' | 'manual' | 'ai_tailor' | 'ai_enrich' | 'wizard' | 'restore' | 'tex_edit';

export type TexSourceMode = 'generated' | 'edited';

export interface VersionSummary {
  version_id: string;
  resume_id: string;
  workspace_id: string;
  parent_version_id: string | null;
  content_hash: string;
  label: string | null;
  origin: VersionOrigin;
  origin_ref: string | null;
  is_pinned: boolean;
  is_head: boolean;
  tex_source_mode: TexSourceMode;
  created_at: string;
}

export interface VersionDetail extends VersionSummary {
  document: ResumeDocument;
  tex_source: string | null;
}

export interface VersionListResponse {
  versions: VersionSummary[];
  next_cursor: string | null;
}

async function readError(response: Response, fallback: string): Promise<never> {
  let detail = fallback;
  try {
    const body = await response.json();
    if (typeof body?.detail === 'string') detail = body.detail;
  } catch {
    // Non-JSON error body; keep the fallback message.
  }
  throw new Error(detail);
}

export async function listVersions(
  resumeId: string,
  options: { limit?: number; cursor?: string } = {}
): Promise<VersionListResponse> {
  const params = new URLSearchParams();
  if (options.limit) params.set('limit', String(options.limit));
  if (options.cursor) params.set('cursor', options.cursor);
  const query = params.toString();
  const response = await apiFetch(
    `/api/v1/resumes/${resumeId}/versions${query ? `?${query}` : ''}`
  );
  if (!response.ok) await readError(response, 'Failed to load version history');
  return (await response.json()) as VersionListResponse;
}

export async function fetchVersion(versionId: string): Promise<VersionDetail> {
  const response = await apiFetch(`/api/v1/versions/${versionId}`);
  if (!response.ok) await readError(response, 'Failed to load version');
  return (await response.json()) as VersionDetail;
}

export async function updateVersion(
  versionId: string,
  payload: { label?: string | null; is_pinned?: boolean }
): Promise<VersionDetail> {
  const response = await apiPatch(`/api/v1/versions/${versionId}`, payload);
  if (!response.ok) await readError(response, 'Failed to update version');
  return (await response.json()) as VersionDetail;
}

export async function deleteVersion(versionId: string): Promise<void> {
  const response = await apiDelete(`/api/v1/versions/${versionId}`);
  if (!response.ok) await readError(response, 'Failed to delete version');
}

export async function restoreVersion(resumeId: string, versionId: string): Promise<VersionSummary> {
  const response = await apiPost(`/api/v1/resumes/${resumeId}/restore`, {
    version_id: versionId,
  });
  if (!response.ok) await readError(response, 'Failed to restore version');
  return (await response.json()) as VersionSummary;
}
