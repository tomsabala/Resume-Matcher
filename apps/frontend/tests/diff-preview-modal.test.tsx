import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { DiffPreviewModal } from '@/components/tailor/diff-preview-modal';
import { makeDocumentDiff, makeRow, makeSectionDiff, makeStats } from './fixtures/diff';

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({
    t: (key: string) => key,
  }),
}));

const summaryPath = 'sections.summary.text';
const bulletPath = 'sections.experience.entries[0].bullets[0].text';

const diff = makeDocumentDiff({
  stats: makeStats({ bullets_modified: 1, total_changes: 2 }),
  sections: [
    makeSectionDiff({
      base_key: 'summary',
      head_key: 'summary',
      base_heading: 'Summary',
      head_heading: 'Summary',
      rows: [
        makeRow({
          kind: 'text',
          status: 'modified',
          path: summaryPath,
          base_text: 'Engineer',
          head_text: 'Staff engineer',
        }),
      ],
    }),
    makeSectionDiff({
      rows: [makeRow({ status: 'added', path: bulletPath, head_text: 'Shipped the migration' })],
    }),
  ],
});

describe('DiffPreviewModal', () => {
  it('renders fallback dialog when diff data is missing', () => {
    const onClose = vi.fn();
    const onConfirm = vi.fn();
    render(<DiffPreviewModal isOpen onClose={onClose} onReject={vi.fn()} onConfirm={onConfirm} />);

    expect(screen.getByText('tailor.missingDiffDialog.title')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.missingDiffDialog.confirmLabel' }));
    expect(onConfirm).toHaveBeenCalledWith(null);
  });

  it('accepts the whole preview by default', () => {
    const onConfirm = vi.fn();
    render(
      <DiffPreviewModal
        isOpen
        onClose={vi.fn()}
        onReject={vi.fn()}
        onConfirm={onConfirm}
        diff={diff}
      />
    );

    expect(screen.getByText('Staff engineer')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'tailor.diffModal.confirmButton' }));
    // `null` means "take everything", including changes no single row owns.
    expect(onConfirm).toHaveBeenCalledWith(null);
  });

  it('confirms only the rows left ticked', () => {
    const onConfirm = vi.fn();
    render(
      <DiffPreviewModal
        isOpen
        onClose={vi.fn()}
        onReject={vi.fn()}
        onConfirm={onConfirm}
        diff={diff}
      />
    );

    const boxes = screen.getAllByRole('checkbox');
    expect(boxes).toHaveLength(2);
    fireEvent.click(boxes[0]);
    fireEvent.click(screen.getByRole('button', { name: 'tailor.diffModal.confirmButton' }));

    expect(onConfirm).toHaveBeenCalledWith([bulletPath]);
  });

  it('cannot confirm an empty selection', () => {
    const onConfirm = vi.fn();
    render(
      <DiffPreviewModal
        isOpen
        onClose={vi.fn()}
        onReject={vi.fn()}
        onConfirm={onConfirm}
        diff={diff}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'diff.clearAll' }));
    const confirm = screen.getByRole('button', { name: 'tailor.diffModal.confirmButton' });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('fires the reject handler', () => {
    const onReject = vi.fn();
    render(
      <DiffPreviewModal
        isOpen
        onClose={vi.fn()}
        onReject={onReject}
        onConfirm={vi.fn()}
        diff={diff}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'tailor.diffModal.rejectButton' }));
    expect(onReject).toHaveBeenCalledTimes(1);
  });
});
