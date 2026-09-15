/**
 * Workspace API
 *
 * A workspace is a named owner profile that scopes resumes, job descriptions
 * and tracker cards. The active one is sent on every request as
 * `X-Workspace-Id` (see `lib/api/client.ts`).
 */

import { apiFetch, apiPost, apiPatch, apiDelete } from './client';

export interface Workspace {
  workspace_id: string;
  name: string;
  slug: string;
  content_language: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceCreate {
  name: string;
  content_language?: string;
}

export interface WorkspaceUpdate {
  name?: string;
  content_language?: string;
  is_default?: boolean;
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

export async function listWorkspaces(): Promise<Workspace[]> {
  const response = await apiFetch('/api/v1/workspaces');
  if (!response.ok) await readError(response, 'Failed to load workspaces');
  const data = await response.json();
  return data.workspaces as Workspace[];
}

export async function createWorkspace(payload: WorkspaceCreate): Promise<Workspace> {
  const response = await apiPost('/api/v1/workspaces', payload);
  if (!response.ok) await readError(response, 'Failed to create workspace');
  return (await response.json()) as Workspace;
}

export async function updateWorkspace(
  workspaceId: string,
  payload: WorkspaceUpdate
): Promise<Workspace> {
  const response = await apiPatch(`/api/v1/workspaces/${workspaceId}`, payload);
  if (!response.ok) await readError(response, 'Failed to update workspace');
  return (await response.json()) as Workspace;
}

export async function deleteWorkspace(workspaceId: string): Promise<void> {
  const response = await apiDelete(`/api/v1/workspaces/${workspaceId}`);
  if (!response.ok) await readError(response, 'Failed to delete workspace');
}
