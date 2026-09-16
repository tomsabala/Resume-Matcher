import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { AIFailurePanel } from '@/components/dashboard/ai-failure-panel';
import { dismissAIFailures, fetchAIFailures, type AIFailure } from '@/lib/api/diagnostics';

/**
 * A truncated or rejected model answer used to reach the user as a generic
 * "please try again", with the reason only in the server log.
 */
vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({
    t: (key: string, params?: Record<string, string | number>) =>
      params ? `${key}:${Object.values(params).join(',')}` : key,
    locale: 'en',
  }),
}));

vi.mock('@/lib/api/diagnostics', () => ({
  fetchAIFailures: vi.fn(),
  dismissAIFailures: vi.fn(),
}));

const mockedFetch = vi.mocked(fetchAIFailures);
const mockedDismiss = vi.mocked(dismissAIFailures);

const TRUNCATED: AIFailure = {
  id: 'f-1',
  at: '2026-09-16T08:30:00+00:00',
  operation: 'resume',
  kind: 'truncated',
  detail: 'JSON response truncated: 1 unclosed object(s) after 5671 characters',
  model: 'anthropic/claude-opus-5',
  provider: 'anthropic',
  attempts: 3,
  max_tokens: 32768,
};

beforeEach(() => {
  mockedFetch.mockReset();
  mockedDismiss.mockReset();
  mockedDismiss.mockResolvedValue(1);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('AIFailurePanel', () => {
  it('names the reason and the budget it ran into', async () => {
    mockedFetch.mockResolvedValue([TRUNCATED]);

    render(<AIFailurePanel />);

    expect(await screen.findByText('dashboard.aiFailures.kinds.truncated')).toBeInTheDocument();
    expect(screen.getByText(/5671 characters/)).toBeInTheDocument();
    expect(screen.getByText('dashboard.aiFailures.budget:32768')).toBeInTheDocument();
    expect(screen.getByText('dashboard.aiFailures.attempts:3')).toBeInTheDocument();
    // The budget case is the one with an actionable fix.
    expect(screen.getByText('dashboard.aiFailures.hintTruncated')).toBeInTheDocument();
  });

  it('stays invisible when nothing has failed', async () => {
    mockedFetch.mockResolvedValue([]);

    render(<AIFailurePanel />);

    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    expect(screen.queryByText('dashboard.aiFailures.title')).not.toBeInTheDocument();
  });

  it('omits the budget hint for a failure a bigger budget cannot fix', async () => {
    mockedFetch.mockResolvedValue([
      { ...TRUNCATED, id: 'f-2', kind: 'provider', detail: 'Invalid API key' },
    ]);

    render(<AIFailurePanel />);

    expect(await screen.findByText('dashboard.aiFailures.kinds.provider')).toBeInTheDocument();
    expect(screen.queryByText('dashboard.aiFailures.hintTruncated')).not.toBeInTheDocument();
  });

  it('dismisses server-side, not just locally', async () => {
    mockedFetch.mockResolvedValue([TRUNCATED]);

    render(<AIFailurePanel />);
    const dismiss = await screen.findByRole('button', { name: 'dashboard.aiFailures.dismiss' });
    dismiss.click();

    await waitFor(() => expect(mockedDismiss).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.queryByText('dashboard.aiFailures.title')).not.toBeInTheDocument()
    );
  });

  it('never breaks the dashboard when diagnostics themselves fail', async () => {
    mockedFetch.mockRejectedValue(new Error('status 500'));

    render(<AIFailurePanel />);

    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    expect(screen.queryByText('dashboard.aiFailures.title')).not.toBeInTheDocument();
  });
});
