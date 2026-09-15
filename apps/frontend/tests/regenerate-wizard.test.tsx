import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { RegenerateDialog, type RegenerateGroup } from '@/components/builder/regenerate-dialog';
import { RegenerateDiffPreview } from '@/components/builder/regenerate-diff-preview';
import type { RegenerateItemInput, RegeneratedItem } from '@/lib/api/enrichment';

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({
    t: (key: string) => {
      if (key === 'builder.regenerate.selectDialog.itemCount.one') {
        return '{count} item';
      }
      if (key === 'builder.regenerate.selectDialog.itemCount.other') {
        return '{count} items';
      }
      return key;
    },
  }),
}));

describe('RegenerateDialog', () => {
  it('renders a dedicated empty-state message when there are no items', () => {
    render(
      <RegenerateDialog
        open
        onOpenChange={vi.fn()}
        groups={[]}
        selectedItems={[]}
        onSelectionChange={vi.fn()}
        onContinue={vi.fn()}
      />
    );

    expect(
      screen.getByText('builder.regenerate.selectDialog.noItemsAvailable')
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'builder.regenerate.selectDialog.continueButton' })
    ).toBeDisabled();
  });

  it('uses i18n pluralization keys for content counts', () => {
    const groups: RegenerateGroup[] = [
      {
        key: 'experience',
        heading: 'Experience',
        items: [
          {
            item_id: 'experience:e1',
            item_type: 'entry',
            title: 'Senior Software Engineer',
            subtitle: 'Google',
            current_content: ['Did thing'],
          },
          {
            item_id: 'experience:e2',
            item_type: 'entry',
            title: 'Staff Engineer',
            subtitle: 'Acme',
            current_content: ['Did A', 'Did B'],
          },
        ],
      },
    ];

    render(
      <RegenerateDialog
        open
        onOpenChange={vi.fn()}
        groups={groups}
        selectedItems={[]}
        onSelectionChange={vi.fn()}
        onContinue={vi.fn()}
      />
    );

    expect(screen.getByText('1 item')).toBeInTheDocument();
    expect(screen.getByText('2 items')).toBeInTheDocument();
  });

  it('groups by the document section heading, including sections it has never heard of', () => {
    const groups: RegenerateGroup[] = [
      {
        key: 'military_service',
        heading: 'Military Service',
        items: [
          {
            item_id: 'military_service:e1',
            item_type: 'entry',
            title: 'Signals Officer',
            subtitle: 'Royal Corps of Signals',
            current_content: ['Ran the radio net'],
          },
        ],
      },
    ];

    render(
      <RegenerateDialog
        open
        onOpenChange={vi.fn()}
        groups={groups}
        selectedItems={[]}
        onSelectionChange={vi.fn()}
        onContinue={vi.fn()}
      />
    );

    const groupToggle = screen.getByRole('button', { name: /Military Service/i });
    expect(groupToggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: /Signals Officer/i })).toBeInTheDocument();

    // Collapsing hides the section's items but keeps the section itself.
    fireEvent.click(groupToggle);
    expect(groupToggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: /Signals Officer/i })).not.toBeInTheDocument();
  });

  it('enables Continue after selecting an item', () => {
    const groups: RegenerateGroup[] = [
      {
        key: 'experience',
        heading: 'Experience',
        items: [
          {
            item_id: 'experience:e1',
            item_type: 'entry',
            title: 'Senior Software Engineer',
            subtitle: 'Google',
            current_content: ['Did thing'],
          },
        ],
      },
    ];

    const onContinue = vi.fn();

    const Wrapper = () => {
      const [selectedItems, setSelectedItems] = React.useState<RegenerateItemInput[]>([]);
      return (
        <RegenerateDialog
          open
          onOpenChange={vi.fn()}
          groups={groups}
          selectedItems={selectedItems}
          onSelectionChange={setSelectedItems}
          onContinue={onContinue}
        />
      );
    };

    render(<Wrapper />);

    const continueButton = screen.getByRole('button', {
      name: 'builder.regenerate.selectDialog.continueButton',
    });
    expect(continueButton).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /Senior Software Engineer/i }));
    expect(continueButton).toBeEnabled();
  });
});

it('offers refresh retry after saved changes and prevents rejecting an applied result', () => {
  render(
    <RegenerateDiffPreview
      open
      onOpenChange={vi.fn()}
      regeneratedItems={[]}
      error="Refresh failed"
      onAccept={vi.fn()}
      onReject={vi.fn()}
      isApplying={false}
      needsRefresh
    />
  );
  expect(screen.getByText('builder.regenerate.errors.refreshFailed')).toBeVisible();
  expect(
    screen.getByRole('button', { name: 'builder.regenerate.diffPreview.retryRefresh' })
  ).toBeEnabled();
  expect(
    screen.getByRole('button', { name: 'builder.regenerate.diffPreview.rejectButton' })
  ).toBeDisabled();
});

describe('RegenerateDiffPreview', () => {
  it('renders the server-computed rows under a human-friendly title', () => {
    const regeneratedItems: RegeneratedItem[] = [
      {
        item_id: 'experience:e1',
        item_type: 'entry',
        title: 'Senior Software Engineer',
        subtitle: 'Google',
        original_content: ['Old bullet'],
        new_content: ['New bullet'],
        rows: [
          {
            kind: 'bullet',
            status: 'modified',
            path: 'experience:e1[0]',
            base_text: 'Old bullet',
            head_text: 'New bullet',
            spans: [
              { side: 'base', start: 0, end: 3, op: 'replace' },
              { side: 'head', start: 0, end: 3, op: 'replace' },
            ],
            anchor: { index: 0 },
          },
        ],
        diff_summary: 'Summary',
      },
    ];

    render(
      <RegenerateDiffPreview
        open
        onOpenChange={vi.fn()}
        regeneratedItems={regeneratedItems}
        error={null}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isApplying={false}
      />
    );

    expect(screen.getByText('Senior Software Engineer | Google')).toBeInTheDocument();
    expect(screen.queryByText('experience:e1')).not.toBeInTheDocument();

    // Both sides of the proposal, with the changed words marked.
    expect(screen.getByText(/Old/)).toBeInTheDocument();
    expect(screen.getByText(/New/)).toBeInTheDocument();
    expect(document.body.querySelector('[data-status="modified"]')?.className).toContain(
      'border-l-4 border-orange-500'
    );
  });
});
