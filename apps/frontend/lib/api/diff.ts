/**
 * Structured document comparison.
 *
 * Every diff in the app — resume vs resume, version vs version, resume vs an AI
 * proposal — is computed by `POST /api/v1/diff` (or embedded in a tailoring
 * response) and rendered by one component tree. These types mirror
 * `app/schemas/diff.py` exactly; nothing here computes a diff.
 */

import { apiPost } from './client';

export type RowKind = 'entry' | 'bullet' | 'tag' | 'group' | 'text' | 'line';

export type RowStatus = 'added' | 'removed' | 'modified' | 'moved' | 'unchanged';

export type SectionStatus = 'added' | 'removed' | 'renamed' | 'modified' | 'moved' | 'unchanged';

/** A character range within one side of a modified row. */
export interface DiffSpan {
  side: 'base' | 'head';
  start: number;
  end: number;
  op: 'insert' | 'delete' | 'replace';
}

/** Where a row lives, for scroll-to and partial accept. */
export interface DiffAnchor {
  section_id?: string | null;
  section_key?: string | null;
  entry_id?: string | null;
  index?: number | null;
}

/** One comparable line of the document. */
export interface DiffRow {
  kind: RowKind;
  status: RowStatus;
  path: string;
  base_text?: string | null;
  head_text?: string | null;
  /** Only populated on `modified` rows; offsets index the matching side's text. */
  spans: DiffSpan[];
  anchor: DiffAnchor;
}

/** One section's rows, plus how the section itself changed. */
export interface SectionDiff {
  status: SectionStatus;
  base_key: string | null;
  head_key: string | null;
  base_heading: string | null;
  head_heading: string | null;
  base_index: number | null;
  head_index: number | null;
  rows: DiffRow[];
}

/** Counts for the summary bar. */
export interface DiffStats {
  sections_added: number;
  sections_removed: number;
  sections_renamed: number;
  sections_moved: number;
  entries_added: number;
  entries_removed: number;
  entries_modified: number;
  entries_moved: number;
  bullets_added: number;
  bullets_removed: number;
  bullets_modified: number;
  tags_added: number;
  tags_removed: number;
  total_changes: number;
}

/** A whole comparison, grouped by section. */
export interface DocumentDiff {
  stats: DiffStats;
  header: DiffRow[];
  sections: SectionDiff[];
}

/** Line diff over LaTeX source. */
export interface TexDiff {
  rows: DiffRow[];
}

/** One side of a comparison. Exactly one field may be set. */
export interface DiffRef {
  version_id?: string;
  resume_id?: string;
}

export interface CompareOptions {
  /** Unchanged rows kept around each change; 0 returns changes only. */
  context?: number;
}

export function resumeRef(resumeId: string): DiffRef {
  return { resume_id: resumeId };
}

export function versionRef(versionId: string): DiffRef {
  return { version_id: versionId };
}

/**
 * Reads a `resume:<id>` / `version:<id>` query-string token.
 *
 * The Compare screen is linkable, so a ref has to survive a URL round trip;
 * anything else is a malformed link rather than a server error.
 */
export function parseRefToken(token: string | null | undefined): DiffRef | null {
  if (!token) return null;
  const separator = token.indexOf(':');
  if (separator <= 0) return null;
  const kind = token.slice(0, separator);
  const id = token.slice(separator + 1).trim();
  if (!id) return null;
  if (kind === 'resume') return resumeRef(id);
  if (kind === 'version') return versionRef(id);
  return null;
}

export function formatRefToken(ref: DiffRef): string {
  return ref.version_id ? `version:${ref.version_id}` : `resume:${ref.resume_id ?? ''}`;
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

export async function compareDocuments(
  base: DiffRef,
  head: DiffRef,
  options: CompareOptions = {}
): Promise<DocumentDiff> {
  const response = await apiPost('/diff', {
    base,
    head,
    mode: 'document',
    ...(options.context === undefined ? {} : { context: options.context }),
  });
  if (!response.ok) await readError(response, 'Failed to compare documents');
  return (await response.json()) as DocumentDiff;
}

export async function compareTexSources(
  base: DiffRef,
  head: DiffRef,
  options: CompareOptions = {}
): Promise<TexDiff> {
  const response = await apiPost('/diff', {
    base,
    head,
    mode: 'tex',
    ...(options.context === undefined ? {} : { context: options.context }),
  });
  if (!response.ok) await readError(response, 'Failed to compare LaTeX sources');
  return (await response.json()) as TexDiff;
}
