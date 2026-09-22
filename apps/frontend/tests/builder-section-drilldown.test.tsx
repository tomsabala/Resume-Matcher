import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { ResumeForm } from '@/components/builder/resume-form';
import { SCHEMA_VERSION, type ResumeDocument, type Section } from '@/lib/types/document';

/**
 * The flat editor nests pane padding, a 44px section drag gutter, a section card,
 * a 44px entry drag gutter and an entry card, leaving a bullet field 107px wide
 * (~5 characters) at 375px. The phone editor is a two-level drill-down instead:
 * an index of sections, then one section's fields with neither gutter.
 *
 * The `pl-11` assertion is the whole width win — restoring a drag gutter inside
 * the section editor is exactly what a careless refactor would do.
 */

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key }),
}));

function section(id: string, heading: string, kind: 'entries' | 'tags'): Section {
  return {
    id,
    key: id,
    heading,
    kind,
    visible: true,
    column: 'main',
    text: '',
    entries:
      kind === 'entries'
        ? [
            {
              id: `${id}-e1`,
              title: 'Engineer',
              subtitle: 'ACME',
              meta: '',
              period: '2020',
              links: [],
              summary: '',
              bullets: [{ text: 'Shipped the thing', style: 'bullet' }],
            },
          ]
        : [],
    tags: kind === 'tags' ? ['Rust'] : [],
    groups: [],
  };
}

const doc: ResumeDocument = {
  schemaVersion: SCHEMA_VERSION,
  header: { name: 'Ada Lovelace', headline: 'Engineer', contacts: [] },
  sections: [section('sec-exp', 'Experience', 'entries'), section('sec-skills', 'Skills', 'tags')],
};

beforeEach(() => {
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
});

function renderForm() {
  const onOpenFormatting = vi.fn();
  render(<ResumeForm doc={doc} onUpdate={vi.fn()} onOpenFormatting={onOpenFormatting} />);
  return { onOpenFormatting };
}

describe('builder section drill-down on mobile', () => {
  it('opens on an index of sections, not on the fields', () => {
    renderForm();

    expect(screen.getByText('builder.sections.title')).toBeInTheDocument();
    expect(screen.getByText('Experience')).toBeInTheDocument();
    expect(screen.getByText('Skills')).toBeInTheDocument();
    // No section's fields are mounted yet.
    expect(screen.queryByDisplayValue('Engineer')).toBeNull();
    // No drag gutter: the index is rows, not draggable cards.
    expect(document.querySelectorAll('.pl-11')).toHaveLength(0);
  });

  it('shows one section at a time and returns to the index', async () => {
    renderForm();

    await act(async () => {
      fireEvent.click(screen.getByText('Experience'));
    });

    expect(screen.getByDisplayValue('Engineer')).toBeInTheDocument();
    expect(screen.queryByText('Skills')).toBeNull();
    expect(screen.queryByText('builder.sections.title')).toBeNull();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'common.back' }));
    });

    expect(screen.getByText('builder.sections.title')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Engineer')).toBeNull();
  });

  it('renders the section editor without a drag gutter', async () => {
    renderForm();

    await act(async () => {
      fireEvent.click(screen.getByText('Experience'));
    });

    expect(document.querySelectorAll('.pl-11')).toHaveLength(0);
  });

  it('brings the gutter back only while reordering', async () => {
    renderForm();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'builder.sections.reorder' }));
    });

    expect(document.querySelectorAll('.pl-11')).toHaveLength(doc.sections.length);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'common.finish' }));
    });

    expect(document.querySelectorAll('.pl-11')).toHaveLength(0);
  });

  it('routes formatting to the sheet instead of rendering it inline', async () => {
    const { onOpenFormatting } = renderForm();

    await act(async () => {
      fireEvent.click(screen.getByText('builder.formatting.panelTitle'));
    });

    expect(onOpenFormatting).toHaveBeenCalled();
  });
});
