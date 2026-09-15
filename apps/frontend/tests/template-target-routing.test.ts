import { beforeEach, describe, expect, it, vi } from 'vitest';
import { downloadResumePdf, getResumePdfUrl } from '@/lib/api/resume';
import { compileTexPdf } from '@/lib/api/tex';
import { apiFetch } from '@/lib/api/client';
import { DEFAULT_TEMPLATE_SETTINGS } from '@/lib/types/template-settings';

vi.mock('@/lib/api/tex', () => ({ compileTexPdf: vi.fn() }));

vi.mock('@/lib/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const compile = vi.mocked(compileTexPdf);
const fetchApi = vi.mocked(apiFetch);

/**
 * One picker, two renderers. Before this, a LaTeX selection still produced a
 * `/pdf` URL with fifteen HTML-only query parameters, so Download PDF quietly
 * exported the Chromium rendering of a document the user had chosen the engine
 * for.
 */
describe('resume export routing', () => {
  beforeEach(() => {
    compile.mockReset();
    compile.mockResolvedValue(new Blob(['%PDF-1.7'], { type: 'application/pdf' }));
    fetchApi.mockReset();
    // jsdom's Blob has no stream(), so a real Response cannot wrap one.
    fetchApi.mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => new Blob(['%PDF-1.7'], { type: 'application/pdf' }),
    } as unknown as Response);
  });

  it('refuses to build a browser PDF URL for a LaTeX template', () => {
    expect(() =>
      getResumePdfUrl('r-1', { ...DEFAULT_TEMPLATE_SETTINGS, template: 'tex-classic' })
    ).toThrow(/tex-classic/);
  });

  it('compiles a LaTeX selection with its template and page size', async () => {
    await downloadResumePdf(
      'r-1',
      { ...DEFAULT_TEMPLATE_SETTINGS, template: 'tex-compact', pageSize: 'LETTER' },
      'en'
    );

    expect(compile).toHaveBeenCalledWith('r-1', 'tex-compact', 'LETTER');
    expect(fetchApi).not.toHaveBeenCalled();
  });

  it('still renders an HTML selection through the print route', async () => {
    await downloadResumePdf(
      'r-1',
      { ...DEFAULT_TEMPLATE_SETTINGS, template: 'swiss-single' },
      'en'
    );

    expect(compile).not.toHaveBeenCalled();
    const url = fetchApi.mock.calls[0][0];
    expect(url).toContain('/resumes/r-1/pdf?');
    expect(url).toContain('template=swiss-single');
  });
});
