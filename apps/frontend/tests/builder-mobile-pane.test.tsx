import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, cleanup, fireEvent } from '@testing-library/react';
import React from 'react';
import { sampleDocument } from './fixtures/document';
import { ResumeBuilder } from '@/components/builder/resume-builder';

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

vi.mock('@/lib/i18n', () => {
  const t = (key: string) => key;
  return { useTranslations: () => ({ t }) };
});

vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({ incrementResumes: vi.fn(), setHasMasterResume: vi.fn() }),
}));

vi.mock('@/lib/context/language-context', () => ({
  useLanguage: () => ({ uiLanguage: 'en', contentLanguage: 'en' }),
}));

vi.mock('@/components/common/resume_previewer_context', () => ({
  useResumePreview: () => ({ improvedData: null }),
}));

// The pane switch is layout, not content: stub the heavy editor/preview trees.
vi.mock('@/components/preview', () => ({ PaginatedPreview: () => null }));
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

beforeEach(() => {
  fetchResume.mockReset();
  fetchResume.mockResolvedValue({ processed_resume: sampleDocument() });
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/**
 * Below `lg` the two-pane split gives each pane ~270px of height and loses the
 * side-by-side comparison anyway, so exactly one pane is shown and the user
 * switches between them. Desktop must keep both, hence the `lg:` escape hatches.
 */
describe('builder mobile pane switch', () => {
  it('shows one pane at a time on mobile while keeping both at lg', async () => {
    await act(async () => {
      render(<ResumeBuilder />);
    });

    const editor = screen.getByTestId('builder-editor-pane');
    const preview = screen.getByTestId('builder-preview-pane');

    expect(editor).toHaveClass('block');
    expect(editor).not.toHaveClass('hidden');
    expect(preview).toHaveClass('hidden');
    expect(preview).not.toHaveClass('flex');

    await act(async () => {
      fireEvent.click(screen.getByText('builder.pane.preview'));
    });

    expect(editor).toHaveClass('hidden');
    expect(editor).not.toHaveClass('block');
    expect(preview).toHaveClass('flex');
    expect(preview).not.toHaveClass('hidden');

    // Desktop is unaffected: both panes keep their lg override in either state.
    expect(editor).toHaveClass('lg:block');
    expect(preview).toHaveClass('lg:flex');
  });
});
