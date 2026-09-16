import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import ResumeViewerPage from '@/app/(default)/resumes/[id]/page';
import { downloadResumePdf, fetchResume, type ResumeDetail } from '@/lib/api/resume';
import { TEMPLATE_SETTINGS_STORAGE_KEY } from '@/lib/utils/template-settings-storage';
import { sampleDocument } from './fixtures/document';

/**
 * The viewer used to render and export with the defaults, so a template chosen
 * in the builder was invisible here — the builder is the only place the choice
 * is made, and it is stored per browser, not per resume.
 */
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({ id: 'resume-123' }),
}));
vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (key: string) => key }) }));
vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({ decrementResumes: vi.fn(), setHasMasterResume: vi.fn() }),
}));
vi.mock('@/lib/context/language-context', () => ({ useLanguage: () => ({ uiLanguage: 'en' }) }));
vi.mock('@/components/enrichment/enrichment-modal', () => ({ EnrichmentModal: () => null }));
vi.mock('@/components/dashboard/resume-component', () => ({
  default: ({ settings }: { settings?: { template: string } }) => (
    <div data-testid="html-resume" data-template={settings?.template ?? 'none'} />
  ),
}));
vi.mock('@/components/latex/tex-pdf-preview', () => ({
  TexPdfPreview: ({ template, pageSize }: { template: string; pageSize: string }) => (
    <div data-testid="tex-preview" data-template={template} data-page-size={pageSize} />
  ),
}));
vi.mock('@/lib/api/resume', () => ({
  fetchResume: vi.fn(),
  deleteResume: vi.fn(),
  retryProcessing: vi.fn(),
  renameResume: vi.fn(),
  downloadResumePdf: vi.fn(),
  getResumePdfUrl: vi.fn(),
}));

const mockedFetchResume = vi.mocked(fetchResume);
const mockedDownload = vi.mocked(downloadResumePdf);

const storeTemplate = (settings: Record<string, unknown>) =>
  localStorage.setItem(TEMPLATE_SETTINGS_STORAGE_KEY, JSON.stringify(settings));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mockedFetchResume.mockResolvedValue({
    title: 'My Resume',
    processed_resume: sampleDocument({ summary: 'Stored summary' }),
    raw_resume: { processing_status: 'ready' },
  } as unknown as ResumeDetail);
  mockedDownload.mockResolvedValue(new Blob(['%PDF-1.7'], { type: 'application/pdf' }));
});

describe('ResumeViewerPage template selection', () => {
  it('renders the HTML template the builder stored, not the default', async () => {
    storeTemplate({ template: 'vivid', pageSize: 'A4' });

    render(<ResumeViewerPage />);

    const rendered = await screen.findByTestId('html-resume');
    await waitFor(() => expect(rendered).toHaveAttribute('data-template', 'vivid'));
  });

  it("prefers the resume's own choice over the last one used in this browser", async () => {
    storeTemplate({ template: 'modern', pageSize: 'A4' });
    mockedFetchResume.mockResolvedValue({
      title: 'My Resume',
      processed_resume: sampleDocument({ summary: 'Stored summary' }),
      raw_resume: { processing_status: 'ready' },
      template_settings: { template: 'clean', pageSize: 'A4' },
    } as unknown as ResumeDetail);

    render(<ResumeViewerPage />);

    const rendered = await screen.findByTestId('html-resume');
    await waitFor(() => expect(rendered).toHaveAttribute('data-template', 'clean'));
  });

  it('shows the engine-compiled PDF when a LaTeX template is selected', async () => {
    storeTemplate({ template: 'tex-classic', pageSize: 'LETTER' });

    render(<ResumeViewerPage />);

    const preview = await screen.findByTestId('tex-preview');
    expect(preview).toHaveAttribute('data-template', 'tex-classic');
    expect(preview).toHaveAttribute('data-page-size', 'LETTER');
    expect(screen.queryByTestId('html-resume')).not.toBeInTheDocument();
  });

  it('exports with the stored settings rather than the backend defaults', async () => {
    storeTemplate({ template: 'tex-compact', pageSize: 'LETTER' });

    render(<ResumeViewerPage />);
    const download = await screen.findByRole('button', { name: /resumeViewer.download/i });
    download.click();

    await waitFor(() =>
      expect(mockedDownload).toHaveBeenCalledWith(
        'resume-123',
        expect.objectContaining({ template: 'tex-compact', pageSize: 'LETTER' }),
        'en'
      )
    );
  });
});
