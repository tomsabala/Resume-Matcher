import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Dashboard from '@/app/(default)/dashboard/page';

/**
 * Below `lg` the dashboard is a list, not a card grid: ten 338x338 squares were
 * ~4060px of scroll with per-card actions crammed into four 32px icon buttons.
 * The compare flow is the one interaction here with no desktop equivalent — it
 * replaces two 12px checkboxes with a pick-a-second-row mode.
 */

// `setMaster` is asserted via the confirm dialog it opens, not called directly.

vi.mock('@/lib/context/workspace-context', () => ({
  useWorkspace: () => ({ revision: 0 }),
}));

const list = vi.fn();
const get = vi.fn();
const push = vi.fn();
const setMaster = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: (...a: unknown[]) => push(...a) }),
}));
vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({
    t: (key: string) => key,
    locale: 'en',
  }),
}));
vi.mock('@/lib/context/status-cache', () => ({
  useStatusCache: () => ({
    status: { llm_configured: true },
    isLoading: false,
    incrementResumes: vi.fn(),
    decrementResumes: vi.fn(),
    setHasMasterResume: vi.fn(),
  }),
}));
vi.mock('@/lib/api/resume', () => ({
  fetchResumeList: (...args: unknown[]) => list(...args),
  fetchResume: (...args: unknown[]) => get(...args),
  deleteResume: vi.fn(),
  renameResume: vi.fn(),
  setMasterResume: (...args: unknown[]) => setMaster(...args),
  retryProcessing: vi.fn(),
  fetchJobDescription: vi.fn().mockResolvedValue(null),
}));
vi.mock('@/components/dashboard/resume-upload-dialog', () => ({ ResumeUploadDialog: () => null }));
vi.mock('@/components/dashboard/master-resume-choice-dialog', () => ({
  MasterResumeChoiceDialog: () => null,
}));

const row = (id: string, master = false) => ({
  resume_id: id,
  title: id,
  filename: `${id}.pdf`,
  is_master: master,
  processing_status: 'ready',
  created_at: '2026-01-01',
  updated_at: '2026-01-01',
  parent_id: null,
});

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  window.matchMedia = ((query: string) => ({
    matches: true,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  get.mockResolvedValue({
    processed_resume: { personalInfo: { name: 'Ada' } },
    raw_resume: { processing_status: 'ready' },
  });
  list.mockResolvedValue([row('m', true), row('a'), row('b')]);
});

describe('dashboard mobile list', () => {
  it('renders rows, not cards', async () => {
    await act(async () => {
      render(<Dashboard />);
    });
    expect(document.querySelectorAll('.aspect-square').length).toBe(0);
    expect(screen.getByText('a')).toBeInTheDocument();
    expect(screen.getByText('b')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'common.more' }).length).toBe(3);
  });

  it('compare flow pushes both ids', async () => {
    await act(async () => {
      render(<Dashboard />);
    });
    const more = screen.getAllByRole('button', { name: 'common.more' });
    await act(async () => {
      fireEvent.click(more[1]);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'dashboard.selection.compare' }));
    });
    expect(screen.getByText('dashboard.compare.pickSecond')).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByText('b'));
    });
    expect(push).toHaveBeenCalledWith('/compare?base=resume:a&head=resume:b');
  });

  it('sheet exposes set master / rename / delete but no open', async () => {
    await act(async () => {
      render(<Dashboard />);
    });
    const more = screen.getAllByRole('button', { name: 'common.more' });
    await act(async () => {
      fireEvent.click(more[2]);
    });
    expect(screen.getByRole('button', { name: 'dashboard.manage.setMaster' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'dashboard.manage.rename' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'common.delete' })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'dashboard.manage.setMaster' }));
    });
    expect(screen.getByText('confirmations.setMasterDescription')).toBeInTheDocument();
  });

  it('master row sheet has no set-master item', async () => {
    await act(async () => {
      render(<Dashboard />);
    });
    const more = screen.getAllByRole('button', { name: 'common.more' });
    await act(async () => {
      fireEvent.click(more[0]);
    });
    expect(screen.queryByRole('button', { name: 'dashboard.manage.setMaster' })).toBeNull();
    expect(screen.getByRole('button', { name: 'dashboard.manage.rename' })).toBeInTheDocument();
  });

  it('tapping a row opens the resume', async () => {
    await act(async () => {
      render(<Dashboard />);
    });
    await act(async () => {
      fireEvent.click(screen.getByText('a'));
    });
    expect(push).toHaveBeenCalledWith('/resumes/a');
  });

  it('rename from the sheet opens the rename dialog', async () => {
    await act(async () => {
      render(<Dashboard />);
    });
    const more = screen.getAllByRole('button', { name: 'common.more' });
    await act(async () => {
      fireEvent.click(more[1]);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'dashboard.manage.rename' }));
    });
    expect(screen.getByText('dashboard.manage.renameTitle')).toBeInTheDocument();
  });
});

describe('failed master recovery on mobile', () => {
  it('moves retry and re-upload into the sheet', async () => {
    get.mockResolvedValue({
      processed_resume: { personalInfo: { name: 'Ada' } },
      raw_resume: { processing_status: 'failed' },
    });
    await act(async () => {
      render(<Dashboard />);
    });
    const more = screen.getAllByRole('button', { name: 'common.more' });
    await act(async () => {
      fireEvent.click(more[0]);
    });
    expect(screen.getByRole('button', { name: 'dashboard.retryProcessing' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'dashboard.deleteAndReupload' })).toBeInTheDocument();
  });
});
