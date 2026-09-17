import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Dashboard from '@/app/(default)/dashboard/page';
import ResumeViewerPage from '@/app/(default)/resumes/[id]/page';
import type { ResumeDetail, ResumeListItem } from '@/lib/api/resume';
import { sampleDocument } from './fixtures/document';

const route = vi.hoisted(() => ({ resumeId: 'candidate' }));
const list = vi.fn();
const get = vi.fn();
const promote = vi.fn();
const setHasMasterResume = vi.fn();

// Params land in the rendered string so aria-labels stay distinguishable.
const translate = (key: string, params?: Record<string, string | number>) =>
  params ? `${key}:${Object.values(params).join(',')}` : key;

vi.mock('@/lib/context/workspace-context', () => ({ useWorkspace: () => ({ revision: 0 }) }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({ id: route.resumeId }),
}));
vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: translate, locale: 'en' }) }));
vi.mock('@/lib/context/language-context', () => ({ useLanguage: () => ({ uiLanguage: 'en' }) }));
vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({
    status: { llm_configured: true },
    isLoading: false,
    incrementResumes: vi.fn(),
    decrementResumes: vi.fn(),
    setHasMasterResume,
  }),
}));
vi.mock('@/lib/api/resume', () => ({
  fetchResumeList: (...args: unknown[]) => list(...args),
  fetchResume: (...args: unknown[]) => get(...args),
  setMasterResume: (...args: unknown[]) => promote(...args),
  deleteResume: vi.fn(),
  renameResume: vi.fn(),
  retryProcessing: vi.fn(),
  downloadResumePdf: vi.fn(),
  getResumePdfUrl: vi.fn(() => 'https://example.invalid/pdf'),
  fetchJobDescription: vi.fn().mockResolvedValue(null),
}));
vi.mock('@/components/dashboard/resume-upload-dialog', () => ({ ResumeUploadDialog: () => null }));
vi.mock('@/components/dashboard/master-resume-choice-dialog', () => ({
  MasterResumeChoiceDialog: () => null,
}));
vi.mock('@/components/enrichment/enrichment-modal', () => ({ EnrichmentModal: () => null }));
vi.mock('@/components/dashboard/resume-component', () => ({ default: () => null }));

function row(id: string, overrides: Partial<ResumeListItem> = {}): ResumeListItem {
  return {
    resume_id: id,
    title: id,
    filename: `${id}.pdf`,
    is_master: false,
    processing_status: 'ready',
    created_at: '2026-01-01',
    updated_at: '2026-01-01',
    parent_id: null,
    ...overrides,
  };
}

function detail(overrides: Partial<ResumeDetail> = {}): ResumeDetail {
  return {
    resume_id: route.resumeId,
    is_master: false,
    title: 'Candidate resume',
    processed_resume: sampleDocument({ header: { name: 'Ada' } }),
    raw_resume: {
      id: 1,
      content: 'Ada',
      content_type: 'text/plain',
      created_at: '2026-01-01',
      processing_status: 'ready',
    },
    ...overrides,
  };
}

/** Opens the promote dialog for `title` and presses its confirm button. */
async function promoteFromDashboard(title: string): Promise<void> {
  fireEvent.click(
    await screen.findByRole('button', { name: `dashboard.manage.setMasterResume:${title}` })
  );
  await act(async () =>
    within(screen.getByRole('dialog'))
      .getByRole('button', { name: 'dashboard.manage.setMaster' })
      .click()
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  route.resumeId = 'candidate';
  get.mockResolvedValue(detail());
  promote.mockResolvedValue({
    resume_id: 'candidate',
    is_master: true,
    previous_master_id: 'master-old',
  });
});

describe('promoting a resume from the dashboard', () => {
  it('promotes the confirmed resume and reloads the list with the roles swapped', async () => {
    list
      .mockResolvedValueOnce([row('master-old', { is_master: true }), row('candidate')])
      .mockResolvedValue([row('candidate', { is_master: true }), row('master-old')]);
    render(<Dashboard />);
    await promoteFromDashboard('candidate');

    expect(promote).toHaveBeenCalledWith('candidate');
    expect(localStorage.getItem('master_resume_id')).toBe('candidate');
    expect(setHasMasterResume).toHaveBeenCalledWith(true);
    // The demoted master is an ordinary resume that can be promoted back; the
    // new master no longer offers the action.
    expect(
      screen.getByRole('button', { name: 'dashboard.manage.setMasterResume:master-old' })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'dashboard.manage.setMasterResume:candidate' })
    ).not.toBeInTheDocument();
  });

  it('keeps the current master and reports the failure when promotion fails', async () => {
    promote.mockRejectedValue(new Error('offline'));
    list.mockResolvedValue([row('master-old', { is_master: true }), row('candidate')]);
    render(<Dashboard />);
    await promoteFromDashboard('candidate');

    expect(localStorage.getItem('master_resume_id')).toBe('master-old');
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('dashboard.manage.setMasterFailed')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'dashboard.manage.setMasterResume:candidate' })
    ).toBeInTheDocument();
  });

  it('offers no promotion for a resume that is not ready yet', async () => {
    list.mockResolvedValue([
      row('master-old', { is_master: true }),
      row('half-parsed', { processing_status: 'processing' }),
    ]);
    render(<Dashboard />);
    await act(async () => {});

    expect(
      screen.queryByRole('button', { name: 'dashboard.manage.setMasterResume:half-parsed' })
    ).not.toBeInTheDocument();
  });

  it('labels an unnamed resume by whether it was tailored from another one', async () => {
    list.mockResolvedValue([
      row('master-old', { is_master: true }),
      row('demoted', { title: null, filename: null }),
      row('tailored', { title: null, filename: null, parent_id: 'master-old' }),
    ]);
    render(<Dashboard />);
    await act(async () => {});

    expect(await screen.findByText('dashboard.baseResume')).toBeInTheDocument();
    expect(screen.getByText('dashboard.tailoredResume')).toBeInTheDocument();
  });
});

describe('promoting a resume from its own page', () => {
  it('trusts the server over a stale cached master id', async () => {
    // Another tab promoted a different resume: the cache still names this one.
    localStorage.setItem('master_resume_id', 'candidate');
    render(<ResumeViewerPage />);
    await screen.findByRole('button', { name: 'resumeViewer.setMaster' });

    expect(
      screen.queryByRole('button', { name: 'resumeViewer.enhanceResume' })
    ).not.toBeInTheDocument();
    expect(localStorage.getItem('master_resume_id')).toBeNull();
  });

  it('promotes the open resume and renders it as the master afterwards', async () => {
    render(<ResumeViewerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'resumeViewer.setMaster' }));
    await act(async () =>
      within(screen.getByRole('dialog'))
        .getByRole('button', { name: 'resumeViewer.setMaster' })
        .click()
    );

    expect(promote).toHaveBeenCalledWith('candidate');
    expect(localStorage.getItem('master_resume_id')).toBe('candidate');
    expect(
      await screen.findByRole('button', { name: 'resumeViewer.enhanceResume' })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'resumeViewer.setMaster' })
    ).not.toBeInTheDocument();
  });

  it('stays a non-master resume when promotion fails', async () => {
    promote.mockRejectedValue(new Error('offline'));
    render(<ResumeViewerPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'resumeViewer.setMaster' }));
    await act(async () =>
      within(screen.getByRole('dialog'))
        .getByRole('button', { name: 'resumeViewer.setMaster' })
        .click()
    );

    expect(screen.getByText('dashboard.manage.setMasterFailed')).toBeInTheDocument();
    expect(localStorage.getItem('master_resume_id')).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'resumeViewer.enhanceResume' })
    ).not.toBeInTheDocument();
  });
});
