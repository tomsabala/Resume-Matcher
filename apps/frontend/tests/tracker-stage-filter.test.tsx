import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { KanbanBoard } from '@/components/tracker/kanban-board';
import {
  APPLICATION_STATUS_ORDER,
  listApplications,
  updateApplication,
  type Application,
  type ApplicationColumns,
} from '@/lib/api/tracker';

/**
 * At 375px the seven-column board is seven snap-pages in a ~250px-tall viewport and
 * cross-stage drag is not achievable with a finger. The phone board shows one stage
 * at a time and moves cards through an explicit "Move to…" sheet instead.
 *
 * `data-column` must survive the single-column branch: manage-columns-dialog.test.tsx
 * enumerates stages through that attribute.
 */

vi.mock('@/lib/context/workspace-context', () => ({
  useWorkspace: () => ({ revision: 0 }),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key }),
}));

vi.mock('@/lib/api/tracker', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/tracker')>('@/lib/api/tracker');
  return {
    ...actual,
    listApplications: vi.fn(),
    updateApplication: vi.fn(),
  };
});

const application: Application = {
  application_id: 'app-1',
  job_id: 'job-1',
  resume_id: 'res-1',
  master_resume_id: null,
  status: 'saved',
  company: 'ACME',
  role: 'Engineer',
  applied_at: null,
  notes: null,
  position: 0,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function columnsFixture(): ApplicationColumns {
  const columns = APPLICATION_STATUS_ORDER.reduce((acc, status) => {
    acc[status] = [];
    return acc;
  }, {} as ApplicationColumns);
  columns.saved = [application];
  return columns;
}

function visibleColumns(): string[] {
  return Array.from(document.querySelectorAll('[data-column]')).map(
    (el) => el.getAttribute('data-column') ?? ''
  );
}

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
  vi.mocked(listApplications).mockResolvedValue({ columns: columnsFixture() });
  vi.mocked(updateApplication).mockResolvedValue({ ...application, status: 'response' });
});

async function renderBoard() {
  await act(async () => {
    render(<KanbanBoard />);
  });
  await waitFor(() => expect(visibleColumns().length).toBeGreaterThan(0));
}

describe('tracker stage filter on mobile', () => {
  it('shows exactly one stage instead of a seven-column board', async () => {
    await renderBoard();
    expect(visibleColumns()).toEqual(['saved']);
  });

  it('treats the stage chips as a filter, not a scroll-jump', async () => {
    await renderBoard();

    await act(async () => {
      fireEvent.click(screen.getByRole('tab', { name: /tracker\.columns\.interview/ }));
    });

    expect(visibleColumns()).toEqual(['interview']);
  });

  it('moves a card across stages through the action sheet', async () => {
    await renderBoard();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'common.more' }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'tracker.bulk.moveTo' }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'tracker.columns.response' }));
    });

    expect(updateApplication).toHaveBeenCalledWith('app-1', { status: 'response', position: 0 });
    // The board reloads after the move, so the list request runs a second time.
    await waitFor(() => expect(vi.mocked(listApplications).mock.calls.length).toBeGreaterThan(1));
  });

  it('refuses to offer the stage the card is already in', async () => {
    await renderBoard();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'common.more' }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'tracker.bulk.moveTo' }));
    });

    expect(screen.getByRole('button', { name: 'tracker.columns.saved' })).toBeDisabled();
  });
});
