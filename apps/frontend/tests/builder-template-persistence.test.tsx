import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { fetchResume, saveResumeTemplateSettings, type ResumeDetail } from '@/lib/api/resume';
import { DEFAULT_TEMPLATE_SETTINGS, type TemplateSettings } from '@/lib/types/template-settings';
import { TEMPLATE_SETTINGS_STORAGE_KEY } from '@/lib/utils/template-settings-storage';
import { sampleDocument } from './fixtures/document';

/**
 * The template choice belongs to the resume. It used to live only in
 * localStorage, so it was per browser: the viewer showed the defaults and
 * another device saw nothing of what the user picked.
 */
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams('id=res-1'),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

vi.mock('@/lib/api/resume', () => ({
  fetchResume: vi.fn(),
  updateResume: vi.fn(),
  saveResumeTemplateSettings: vi.fn(),
  downloadResumePdf: vi.fn(),
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
  PaginatedPreview: ({ settings }: { settings: TemplateSettings }) => (
    <div data-testid="html-preview" data-template={settings.template} />
  ),
}));
vi.mock('@/components/latex/tex-pdf-preview', () => ({
  TexPdfPreview: ({ template }: { template: string }) => (
    <div data-testid="tex-preview" data-template={template} />
  ),
}));
vi.mock('@/components/latex/latex-panel', () => ({ LatexPanel: () => null }));
vi.mock('@/components/builder/resume-form', () => ({ ResumeForm: () => null }));
vi.mock('@/components/builder/formatting-controls', () => ({
  FormattingControls: ({
    settings,
    onChange,
  }: {
    settings: TemplateSettings;
    onChange: (next: TemplateSettings) => void;
  }) => (
    <button data-testid="pick-vivid" onClick={() => onChange({ ...settings, template: 'vivid' })}>
      pick
    </button>
  ),
}));
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

const mockedFetch = vi.mocked(fetchResume);
const mockedSave = vi.mocked(saveResumeTemplateSettings);

const RESUME = sampleDocument({ summary: 'Stored summary' });

const resumeWith = (settings: TemplateSettings | null): ResumeDetail =>
  ({
    resume_id: 'res-1',
    title: 'Resume',
    processed_resume: RESUME,
    raw_resume: { processing_status: 'ready' },
    template_settings: settings,
  }) as unknown as ResumeDetail;

const importBuilder = async () =>
  (await import('@/components/builder/resume-builder')).ResumeBuilder;

const mount = async () => {
  const Builder = await importBuilder();
  await act(async () => {
    render(<Builder />);
  });
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  localStorage.clear();
  mockedFetch.mockReset();
  mockedSave.mockReset();
  mockedSave.mockResolvedValue(DEFAULT_TEMPLATE_SETTINGS);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.resetModules();
});

describe('builder template settings persistence', () => {
  it("adopts the resume's own choice over the last one used in this browser", async () => {
    localStorage.setItem(
      TEMPLATE_SETTINGS_STORAGE_KEY,
      JSON.stringify({ ...DEFAULT_TEMPLATE_SETTINGS, template: 'modern' })
    );
    mockedFetch.mockResolvedValue(
      resumeWith({ ...DEFAULT_TEMPLATE_SETTINGS, template: 'tex-classic' })
    );

    await mount();

    const preview = await screen.findByTestId('tex-preview');
    expect(preview).toHaveAttribute('data-template', 'tex-classic');
  });

  it('keeps the last used choice for a resume that has none of its own', async () => {
    localStorage.setItem(
      TEMPLATE_SETTINGS_STORAGE_KEY,
      JSON.stringify({ ...DEFAULT_TEMPLATE_SETTINGS, template: 'clean' })
    );
    mockedFetch.mockResolvedValue(resumeWith(null));

    await mount();

    const preview = await screen.findByTestId('html-preview');
    expect(preview).toHaveAttribute('data-template', 'clean');
  });

  it('stores a new choice on the resume, once, after the change settles', async () => {
    mockedFetch.mockResolvedValue(
      resumeWith({ ...DEFAULT_TEMPLATE_SETTINGS, template: 'swiss-single' })
    );
    await mount();
    await screen.findByTestId('html-preview');
    mockedSave.mockClear();

    await act(async () => {
      screen.getByTestId('pick-vivid').click();
    });
    expect(mockedSave).not.toHaveBeenCalled(); // debounced, not per keystroke

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    await waitFor(() => expect(mockedSave).toHaveBeenCalledTimes(1));
    expect(mockedSave).toHaveBeenCalledWith(
      'res-1',
      expect.objectContaining({ template: 'vivid' })
    );
  });

  it('does not write back the choice it just adopted', async () => {
    mockedFetch.mockResolvedValue(
      resumeWith({ ...DEFAULT_TEMPLATE_SETTINGS, template: 'tex-compact' })
    );

    await mount();
    await screen.findByTestId('tex-preview');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(mockedSave).not.toHaveBeenCalled();
  });
});
