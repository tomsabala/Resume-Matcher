import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { PrepDeck } from '@/components/prep/prep-deck';
import { listPrepCards, updatePrepCard, type PrepCard } from '@/lib/api/prep-cards';

/**
 * The deck is one list with a category switch, and the study dialog is the only
 * thing that writes a confidence rating. `t` is the identity here, so assertions
 * match copy KEYS, not English strings.
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

vi.mock('@/lib/api/prep-cards', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api/prep-cards')>('@/lib/api/prep-cards');
  return {
    ...actual,
    listPrepCards: vi.fn(),
    updatePrepCard: vi.fn(),
    deletePrepCard: vi.fn(),
    generatePrepCards: vi.fn(),
    bulkCreatePrepCards: vi.fn(),
  };
});

function card(overrides: Partial<PrepCard>): PrepCard {
  return {
    card_id: 'c1',
    category: 'technical',
    question: 'What is WAL?',
    answer: 'A write-ahead log.',
    explanation: null,
    examples: null,
    my_answer: null,
    critique: null,
    confidence: 'unrated',
    source: 'manual',
    application_id: null,
    reviewed_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

const TECHNICAL_A = card({ card_id: 'tech-1', question: 'What is WAL?' });
const TECHNICAL_B = card({ card_id: 'tech-2', question: 'What is fsync?' });
const PERSONAL = card({
  card_id: 'pers-1',
  category: 'personal',
  question: 'Why did you leave?',
  answer: null,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listPrepCards).mockResolvedValue({
    cards: [TECHNICAL_A, TECHNICAL_B, PERSONAL],
  });
  vi.mocked(updatePrepCard).mockResolvedValue({ ...TECHNICAL_A, confidence: 'good' });
});

async function renderDeck() {
  await act(async () => {
    render(<PrepDeck />);
  });
  await waitFor(() => expect(screen.getByText('What is WAL?')).toBeInTheDocument());
}

describe('prep deck', () => {
  it('shows only the selected category', async () => {
    await renderDeck();
    expect(screen.getByText('What is fsync?')).toBeInTheDocument();
    expect(screen.queryByText('Why did you leave?')).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'prepDeck.categories.personal' }));
    });

    expect(screen.getByText('Why did you leave?')).toBeInTheDocument();
    expect(screen.queryByText('What is WAL?')).not.toBeInTheDocument();
  });

  it('rates a card from the study dialog and advances to the next one', async () => {
    await renderDeck();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /What is WAL\?/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'prepDeck.card.reveal' }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'prepDeck.confidence.good' }));
    });

    expect(updatePrepCard).toHaveBeenCalledWith('tech-1', { confidence: 'good' });
    // Advanced: the dialog now shows the next card, face-down again.
    const dialog = within(screen.getByRole('dialog'));
    expect(dialog.getByText('What is fsync?')).toBeInTheDocument();
    expect(dialog.getByRole('button', { name: 'prepDeck.card.reveal' })).toBeInTheDocument();
  });

  it('closes the study dialog after rating the last card', async () => {
    await renderDeck();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /What is fsync\?/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'prepDeck.card.reveal' }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'prepDeck.confidence.easy' }));
    });

    expect(updatePrepCard).toHaveBeenCalledWith('tech-2', { confidence: 'easy' });
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'prepDeck.card.reveal' })).toBeNull()
    );
  });

  it('opens the rehearsal dialog rather than the flip game for a personal card', async () => {
    await renderDeck();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'prepDeck.categories.personal' }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Why did you leave\?/ }));
    });

    expect(screen.getByLabelText('prepDeck.personal.myAnswer')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'prepDeck.card.reveal' })).toBeNull();
  });

  it('disables Study until the technical list has a card', async () => {
    vi.mocked(listPrepCards).mockResolvedValue({ cards: [PERSONAL] });
    await act(async () => {
      render(<PrepDeck />);
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'prepDeck.studyAction' })).toBeDisabled()
    );
  });
});
