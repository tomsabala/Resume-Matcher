import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { DiffView } from '@/components/diff/diff-view';
import { makeDocumentDiff, makeRow, makeSectionDiff, makeStats } from './fixtures/diff';

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({
    t: (key: string) => key,
  }),
}));

/** One row of every status, plus a long unchanged run and an intraline change. */
const diff = makeDocumentDiff({
  stats: makeStats({ bullets_added: 1, bullets_removed: 1, bullets_modified: 1, total_changes: 4 }),
  sections: [
    makeSectionDiff({
      rows: [
        makeRow({
          status: 'added',
          path: 'sections.experience.entries[0].bullets[0].text',
          head_text: 'Shipped the migration',
        }),
        makeRow({
          status: 'removed',
          path: 'sections.experience.entries[0].bullets[1].text',
          base_text: 'Did some work',
        }),
        makeRow({
          status: 'modified',
          path: 'sections.experience.entries[0].bullets[2].text',
          base_text: 'Led a small team',
          head_text: 'Led a large team',
          spans: [
            { side: 'base', start: 6, end: 11, op: 'replace' },
            { side: 'head', start: 6, end: 11, op: 'replace' },
          ],
        }),
        makeRow({
          status: 'moved',
          path: 'sections.experience.entries[0].bullets[3].text',
          base_text: 'Mentored juniors',
          head_text: 'Mentored juniors',
        }),
        makeRow({
          status: 'unchanged',
          path: 'sections.experience.entries[1]',
          head_text: 'ctx 1',
        }),
        makeRow({
          status: 'unchanged',
          path: 'sections.experience.entries[2]',
          head_text: 'ctx 2',
        }),
        makeRow({
          status: 'unchanged',
          path: 'sections.experience.entries[3]',
          head_text: 'ctx 3',
        }),
      ],
    }),
    makeSectionDiff({
      status: 'renamed',
      base_key: 'skills',
      head_key: 'core_skills',
      base_heading: 'Skills',
      head_heading: 'Core Skills',
      rows: [
        makeRow({
          kind: 'tag',
          status: 'added',
          path: 'sections.core_skills.tags',
          head_text: 'Go',
        }),
      ],
    }),
  ],
});

describe('DiffView', () => {
  it('marks each row status with a left rule and no tinted background', () => {
    const { container } = render(<DiffView diff={diff} />);

    const rules: Record<string, string> = {
      added: 'border-l-4 border-green-700',
      removed: 'border-l-4 border-red-600',
      modified: 'border-l-4 border-orange-500',
      moved: 'border-l-4 border-blue-700',
    };

    for (const [status, rule] of Object.entries(rules)) {
      const row = container.querySelector(`[data-status="${status}"]`);
      expect(row, status).not.toBeNull();
      expect(row?.className).toContain(rule);
      // Status is the rule, not a fill: the row keeps its white paper.
      expect(row?.className).toContain('bg-white');
    }
  });

  it('collapses a run of unchanged rows until the expander is clicked', () => {
    render(<DiffView diff={diff} />);

    expect(screen.queryByText('ctx 2')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'diff.showUnchangedRows' }));
    expect(screen.getByText('ctx 2')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'diff.hideUnchangedRows' }));
    expect(screen.queryByText('ctx 2')).toBeNull();
  });

  it('renders intraline spans as solid delete and insert marks', () => {
    const { container } = render(<DiffView diff={diff} />);
    const marks = Array.from(container.querySelectorAll('mark'));

    expect(marks.map((mark) => mark.textContent)).toEqual(['small', 'large']);
    expect(marks[0].className).toContain('bg-red-600 text-white');
    expect(marks[1].className).toContain('bg-green-700 text-white');
  });

  it('shows both headings for a renamed section', () => {
    render(<DiffView diff={diff} />);

    expect(screen.getByText('Skills \u2192 Core Skills')).toBeInTheDocument();
  });

  it('offers checkboxes only for selectable content leaves when collecting paths', () => {
    const onAcceptedPathsChange = vi.fn();
    const accepted = [
      'sections.experience.entries[0].bullets[0].text',
      'sections.experience.entries[0].bullets[1].text',
      'sections.experience.entries[0].bullets[2].text',
      'sections.experience.entries[0].bullets[3].text',
      'sections.core_skills.tags',
    ];

    render(
      <DiffView
        diff={diff}
        acceptedPaths={accepted}
        onAcceptedPathsChange={onAcceptedPathsChange}
      />
    );

    // The unchanged entry rows are neither changed nor content leaves.
    const boxes = screen.getAllByRole('checkbox');
    expect(boxes).toHaveLength(accepted.length);
    expect(boxes.every((box) => (box as HTMLInputElement).checked)).toBe(true);

    fireEvent.click(boxes[0]);
    expect(onAcceptedPathsChange).toHaveBeenCalledWith(accepted.slice(1));
  });

  it('renders no checkbox when the caller does not collect paths', () => {
    render(<DiffView diff={diff} />);

    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
  });
});
