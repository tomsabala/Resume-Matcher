import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, cleanup, waitFor } from '@testing-library/react';
import React from 'react';
import { sampleDocument } from './fixtures/document';

/**
 * The preview pane must follow the selected template's renderer. Before the
 * picker was unified, the RESUME pane always showed the browser rendering, so
 * a LaTeX selection previewed a document the export would not produce.
 */
const fetchResume = vi.fn();

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams('id=res-1'),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

vi.mock('@/lib/api/resume', () => ({
  fetchResume: (...args: unknown[]) => fetchResume(...args),
  updateResume: vi.fn(),
  downloadResumePdf: vi.fn(),
  saveResumeTemplateSettings: vi.fn(() => Promise.resolve()),
  downloadCoverLetterPdf: vi.fn(),
  getResumePdfUrl: vi.fn(() => ''),
  getCoverLetterPdfUrl: vi.fn(() => ''),
  updateCoverLetter: vi.fn(),
  updateOutreachMessage: vi.fn(),
  generateCoverLetter: vi.fn(),
  generateOutreachMessage: vi.fn(),
  generateInterviewPrep: vi.fn(),
  fetchJobDescription: vi.fn(() => Promise.resolve(null)),
}));

vi.mock('@/lib/api/tex', () => ({
  getTexCapabilities: vi.fn(() =>
    Promise.resolve({ engine: 'latexmk', can_compile: true, templates: [] })
  ),
}));

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (key: string) => key }) }));
vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({ incrementResumes: vi.fn(), setHasMasterResume: vi.fn() }),
}));
vi.mock('@/lib/context/language-context', () => ({
  useLanguage: () => ({ uiLanguage: 'en', contentLanguage: 'en' }),
}));
vi.mock('@/components/common/resume_previewer_context', () => ({
  useResumePreview: () => ({ improvedData: null }),
}));

vi.mock('@/components/preview', () => ({
  PaginatedPreview: () => <div data-testid="html-preview" />,
}));
vi.mock('@/components/latex/tex-pdf-preview', () => ({
  TexPdfPreview: ({ template, settings }: { template: string; settings: { pageSize: string } }) => (
    <div data-testid="tex-preview" data-template={template} data-page-size={settings.pageSize} />
  ),
}));
vi.mock('@/components/latex/latex-panel', () => ({ LatexPanel: () => null }));
vi.mock('@/components/builder/resume-form', () => ({ ResumeForm: () => null }));
vi.mock('@/components/builder/formatting-controls', () => ({ FormattingControls: () => null }));
vi.mock('@/components/builder/cover-letter-editor', () => ({ CoverLetterEditor: () => null }));
vi.mock('@/components/builder/outreach-editor', () => ({ OutreachEditor: () => null }));
vi.mock('@/components/builder/cover-letter-preview', () => ({ CoverLetterPreview: () => null }));
vi.mock('@/components/builder/outreach-preview', () => ({ OutreachPreview: () => null }));
vi.mock('@/components/builder/generate-prompt', () => ({ GeneratePrompt: () => null }));
vi.mock('@/components/builder/interview-prep-view', () => ({ InterviewPrepView: () => null }));
vi.mock('@/components/builder/jd-comparison-view', () => ({ JDComparisonView: () => null }));
vi.mock('@/components/builder/regenerate-wizard', () => ({ RegenerateWizard: () => null }));
vi.mock('@/hooks/use-regenerate-wizard', () => ({
  useRegenerateWizard: () => ({ step: 'idle', reset: vi.fn() }),
}));

const SETTINGS_KEY = 'resume_builder_settings';
const RESUME = sampleDocument({ summary: 'Stored summary' });

const importBuilder = async () =>
  (await import('@/components/builder/resume-builder')).ResumeBuilder;

const storeSettings = (settings: Record<string, unknown>) =>
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));

beforeEach(() => {
  localStorage.clear();
  fetchResume.mockReset();
  fetchResume.mockResolvedValue({ processed_resume: RESUME, title: 'Resume' });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.resetModules();
});

describe('builder preview target', () => {
  it('previews the engine-compiled PDF for a LaTeX template', async () => {
    storeSettings({ template: 'tex-compact', pageSize: 'LETTER' });
    const Builder = await importBuilder();

    await act(async () => {
      render(<Builder />);
    });

    await waitFor(() => expect(screen.getByTestId('tex-preview')).toBeInTheDocument());
    expect(screen.queryByTestId('html-preview')).not.toBeInTheDocument();
    expect(screen.getByTestId('tex-preview')).toHaveAttribute('data-template', 'tex-compact');
    expect(screen.getByTestId('tex-preview')).toHaveAttribute('data-page-size', 'LETTER');
  });

  it('previews the browser rendering for an HTML template', async () => {
    storeSettings({ template: 'swiss-single', pageSize: 'A4' });
    const Builder = await importBuilder();

    await act(async () => {
      render(<Builder />);
    });

    await waitFor(() => expect(screen.getByTestId('html-preview')).toBeInTheDocument());
    expect(screen.queryByTestId('tex-preview')).not.toBeInTheDocument();
  });

  it('falls back to the default template when storage names an unknown one', async () => {
    storeSettings({ template: 'tex-retired', pageSize: 'A4' });
    const Builder = await importBuilder();

    await act(async () => {
      render(<Builder />);
    });

    await waitFor(() => expect(screen.getByTestId('html-preview')).toBeInTheDocument());
    expect(JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? '{}').template).toBe('swiss-single');
  });
});
