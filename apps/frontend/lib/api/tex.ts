/**
 * LaTeX source and PDF API.
 *
 * Two products from one document: a generated `.tex` the user can download or
 * hand-edit, and a compiled PDF. Compilation is optional — a deployment with
 * no TeX engine still generates and edits source, and `capabilities()` says so
 * up front rather than making the UI discover it from a failed download.
 */

import { apiFetch, apiPut, apiDelete } from './client';
import type { TemplateSettings } from '@/lib/types/template-settings';

export type TexTemplateId = 'tex-classic' | 'tex-compact';

export interface TexSource {
  resume_id: string;
  source: string;
  /** True once the user saved their own source: the document no longer drives it. */
  is_override: boolean;
  template: string;
  engine: string | null;
}

export interface TexCapabilities {
  engine: string | null;
  can_compile: boolean;
  templates: TexTemplateId[];
}

/** A failed compile, carrying the engine log so the user can fix their source. */
export class TexCompileError extends Error {
  constructor(
    message: string,
    readonly log: string
  ) {
    super(message);
    this.name = 'TexCompileError';
  }
}

/** No engine on this host: generation still works, compilation does not. */
export class TexUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TexUnavailableError';
  }
}

async function readError(response: Response, fallback: string): Promise<never> {
  let detail: unknown;
  try {
    detail = (await response.json())?.detail;
  } catch {
    detail = undefined;
  }
  if (detail && typeof detail === 'object' && 'log' in detail) {
    const structured = detail as { message?: string; log?: string };
    throw new TexCompileError(structured.message || fallback, structured.log || '');
  }
  throw new Error(typeof detail === 'string' ? detail : fallback);
}

export async function getTexCapabilities(): Promise<TexCapabilities> {
  const response = await apiFetch('/resumes/tex/capabilities');
  if (!response.ok) await readError(response, 'Failed to read LaTeX capabilities');
  return (await response.json()) as TexCapabilities;
}

/**
 * The formatting controls the LaTeX engine reads.
 *
 * Spelled exactly like the Chromium `/pdf` route's parameters, so one control
 * cannot mean two things across the two renderers. Font family, accent colour
 * and contact icons are HTML-only and deliberately absent.
 */
export type TexFormatSettings = Pick<
  TemplateSettings,
  'pageSize' | 'margins' | 'spacing' | 'fontSize' | 'compactMode'
>;

export function texFormatParams(settings?: TexFormatSettings): URLSearchParams {
  const params = new URLSearchParams();
  params.set('pageSize', settings?.pageSize ?? 'A4');
  if (!settings) return params;
  params.set('marginTop', String(settings.margins.top));
  params.set('marginBottom', String(settings.margins.bottom));
  params.set('marginLeft', String(settings.margins.left));
  params.set('marginRight', String(settings.margins.right));
  params.set('sectionSpacing', String(settings.spacing.section));
  params.set('itemSpacing', String(settings.spacing.item));
  params.set('lineHeight', String(settings.spacing.lineHeight));
  params.set('fontSize', String(settings.fontSize.base));
  params.set('headerScale', String(settings.fontSize.headerScale));
  params.set('compactMode', String(settings.compactMode));
  return params;
}

export async function getTexSource(
  resumeId: string,
  options: {
    template?: TexTemplateId;
    regenerate?: boolean;
    format?: TexFormatSettings;
  } = {}
): Promise<TexSource> {
  const params = texFormatParams(options.format);
  if (options.template) params.set('template', options.template);
  if (options.regenerate) params.set('regenerate', 'true');
  const response = await apiFetch(`/resumes/${resumeId}/tex?${params.toString()}`);
  if (!response.ok) await readError(response, 'Failed to load LaTeX source');
  return (await response.json()) as TexSource;
}

export async function saveTexSource(resumeId: string, source: string): Promise<TexSource> {
  const response = await apiPut(`/resumes/${resumeId}/tex`, { source });
  if (!response.ok) await readError(response, 'Failed to save LaTeX source');
  return (await response.json()) as TexSource;
}

export async function clearTexSource(
  resumeId: string,
  template: TexTemplateId = 'tex-classic',
  format?: TexFormatSettings
): Promise<TexSource> {
  const params = texFormatParams(format);
  params.set('template', template);
  const response = await apiDelete(`/resumes/${resumeId}/tex?${params.toString()}`);
  if (!response.ok) await readError(response, 'Failed to reset LaTeX source');
  return (await response.json()) as TexSource;
}

/**
 * The `.tex` as a blob — the fallback export when no engine exists.
 *
 * Fetched rather than linked: `API_BASE` resolves differently on the server
 * and in the browser, so an `href` built during SSR hydrates mismatched.
 */
export async function downloadTexSource(
  resumeId: string,
  template: TexTemplateId = 'tex-classic',
  format?: TexFormatSettings
): Promise<Blob> {
  const params = texFormatParams(format);
  params.set('template', template);
  const response = await apiFetch(`/resumes/${resumeId}/tex/source?${params.toString()}`);
  if (!response.ok) await readError(response, 'Failed to download LaTeX source');
  return await response.blob();
}

/**
 * Compile and return the PDF as a blob.
 *
 * 503 is a missing engine, 422 is the user's source failing to compile; they
 * lead to different UI, so they get different error types.
 */
export async function compileTexPdf(
  resumeId: string,
  template: TexTemplateId = 'tex-classic',
  format?: TexFormatSettings
): Promise<Blob> {
  const params = texFormatParams(format);
  params.set('template', template);
  const response = await apiFetch(`/resumes/${resumeId}/tex/pdf?${params.toString()}`);
  if (response.status === 503) {
    const detail = await response
      .json()
      .then((body) => body?.detail)
      .catch(() => null);
    throw new TexUnavailableError(
      typeof detail === 'string' ? detail : 'LaTeX compilation is unavailable on this server.'
    );
  }
  if (!response.ok) await readError(response, 'LaTeX compilation failed');
  return await response.blob();
}
