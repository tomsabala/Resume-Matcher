import { describe, expect, it } from 'vitest';
import { render, within } from '@testing-library/react';
import React from 'react';
import type { ResumeDocument } from '@/lib/types/document';

import { ResumeClean } from '@/components/resume/resume-clean';
import { ResumeLatex } from '@/components/resume/resume-latex';
import { ResumeModern } from '@/components/resume/resume-modern';
import { ResumeModernTwoColumn } from '@/components/resume/resume-modern-two-column';
import { ResumeSingleColumn } from '@/components/resume/resume-single-column';
import { ResumeTwoColumn } from '@/components/resume/resume-two-column';
import { ResumeVivid } from '@/components/resume/resume-vivid';
import type { ResumeTemplateProps } from '@/components/resume/template-props';

/**
 * Sections, headings, order and shapes are data: no template may enumerate
 * them. This renders a document that contains
 *
 *   - a section whose key no component has ever heard of (`military_service`),
 *   - one section of every `SectionKind`,
 *   - a sidebar (`column: 'side'`) section, and
 *   - a hidden section,
 *
 * through all seven templates. It fails the moment a template stops routing
 * through `SECTION_KIND_RENDERERS` (or starts special-casing keys), drops a
 * user section that is not a former built-in, leaks a hidden section into the
 * output, or ignores a bullet's `style`.
 */
const buildDoc = (): ResumeDocument => ({
  schemaVersion: 2,
  header: {
    name: 'Ada Lovelace',
    headline: 'Analytical Engineer',
    contacts: [
      { id: 'c1', kind: 'email', label: 'ada@example.com', value: 'ada@example.com', url: '' },
      { id: 'c2', kind: 'location', label: 'London', value: 'London', url: '' },
    ],
  },
  sections: [
    {
      id: 's1',
      key: 'summary',
      heading: 'Summary',
      headingI18nKey: 'resume.sections.summary',
      kind: 'text',
      visible: true,
      column: 'main',
      text: 'SUMMARY PARAGRAPH',
      entries: [],
      tags: [],
      groups: [],
    },
    {
      // A key that exists nowhere in the codebase.
      id: 's2',
      key: 'military_service',
      heading: 'Military Service',
      headingI18nKey: null,
      kind: 'entries',
      visible: true,
      column: 'main',
      text: '',
      entries: [
        {
          id: 'e1',
          title: 'Signals Officer',
          subtitle: 'Royal Corps of Signals',
          meta: 'Aldershot',
          period: 'Spring 2016 - Winter 2019',
          links: [{ kind: 'github', url: 'https://github.com/ada' }],
          summary: 'ENTRY SUMMARY PARAGRAPH',
          bullets: [
            { text: 'PLAIN ROW should have no marker', style: 'plain' },
            { text: 'BULLET ROW should have one', style: 'bullet' },
          ],
        },
      ],
      tags: [],
      groups: [],
    },
    {
      id: 's3',
      key: 'skills',
      heading: 'Skills',
      headingI18nKey: null,
      kind: 'tags',
      visible: true,
      column: 'side',
      text: '',
      entries: [],
      tags: ['Difference Engine', '   ', 'Bernoulli Numbers'],
      groups: [],
    },
    {
      id: 's4',
      key: 'credentials',
      heading: 'Credentials',
      headingI18nKey: null,
      kind: 'groups',
      visible: true,
      column: 'side',
      text: '',
      entries: [],
      tags: [],
      groups: [{ label: 'Certifications', values: ['Note G'] }],
    },
    {
      id: 's5',
      key: 'scratchpad',
      heading: 'Scratchpad',
      headingI18nKey: null,
      kind: 'text',
      visible: false,
      column: 'main',
      text: 'HIDDEN FROM OUTPUT',
      entries: [],
      tags: [],
      groups: [],
    },
  ],
});

const TEMPLATES: [string, React.ComponentType<ResumeTemplateProps>][] = [
  ['ResumeClean', ResumeClean],
  ['ResumeLatex', ResumeLatex],
  ['ResumeModern', ResumeModern],
  ['ResumeModernTwoColumn', ResumeModernTwoColumn],
  ['ResumeSingleColumn', ResumeSingleColumn],
  ['ResumeTwoColumn', ResumeTwoColumn],
  ['ResumeVivid', ResumeVivid],
];

const bulletRow = (container: HTMLElement, text: string): HTMLElement => {
  const row = within(container).getByText(text).closest('li');
  if (!row) throw new Error(`no <li> ancestor for "${text}"`);
  return row as HTMLElement;
};

const markersIn = (row: HTMLElement): string[] =>
  Array.from(row.querySelectorAll('[aria-hidden="true"]'))
    .map((node) => (node.textContent ?? '').trim())
    .filter(Boolean);

describe.each(TEMPLATES)('%s renders sections from data', (_name, Template) => {
  it('renders the header plus every visible section heading', () => {
    const { container } = render(<Template doc={buildDoc()} />);
    const view = within(container);

    // Vivid splits the name into two accent spans, so assert the rendered <h1>.
    expect(container.querySelector('h1')?.textContent).toContain('Ada Lovelace');
    expect(view.getByText('Analytical Engineer')).toBeInTheDocument();
    expect(view.getByText('ada@example.com')).toBeInTheDocument();

    for (const heading of ['Summary', 'Military Service', 'Skills', 'Credentials']) {
      expect(view.getByText(heading)).toBeInTheDocument();
    }
  });

  it('renders one content item for every section kind', () => {
    const { container } = render(<Template doc={buildDoc()} />);
    const view = within(container);

    // text
    expect(view.getByText('SUMMARY PARAGRAPH')).toBeInTheDocument();
    // entries
    expect(view.getByText('Signals Officer')).toBeInTheDocument();
    expect(view.getByText('Royal Corps of Signals')).toBeInTheDocument();
    expect(view.getByText('Aldershot')).toBeInTheDocument();
    expect(view.getByText('Spring 2016 - Winter 2019')).toBeInTheDocument();
    expect(view.getByText('github.com/ada')).toBeInTheDocument();
    expect(view.getByText('ENTRY SUMMARY PARAGRAPH')).toBeInTheDocument();
    expect(view.getByText('BULLET ROW should have one')).toBeInTheDocument();
    // tags (blank values dropped)
    expect(view.getByText('Difference Engine')).toBeInTheDocument();
    expect(view.getByText('Bernoulli Numbers')).toBeInTheDocument();
    // groups
    expect(view.getByText('Certifications')).toBeInTheDocument();
    expect(view.getByText('Note G')).toBeInTheDocument();
  });

  it('honours each bullet style', () => {
    const { container } = render(<Template doc={buildDoc()} />);

    expect(markersIn(bulletRow(container, 'BULLET ROW should have one')).length).toBeGreaterThan(0);
    expect(markersIn(bulletRow(container, 'PLAIN ROW should have no marker'))).toHaveLength(0);
  });

  it('keeps hidden sections out of the output', () => {
    const { container } = render(<Template doc={buildDoc()} />);

    expect(within(container).queryByText('Scratchpad')).toBeNull();
    expect(within(container).queryByText('HIDDEN FROM OUTPUT')).toBeNull();
  });
});

/**
 * The few header shapes that are genuinely template-specific (the section body
 * is shared by construction, the header is not).
 */
describe('template-specific header structure', () => {
  it('ResumeVivid splits the name into two accent tones', () => {
    const { container } = render(<ResumeVivid doc={buildDoc()} />);

    expect(within(container).getByText('Ada')).toBeInTheDocument();
    expect(within(container).getByText('Lovelace')).toBeInTheDocument();
  });

  it('ResumeLatex keeps the location on its own line, out of the contact row', () => {
    const { container } = render(<ResumeLatex doc={buildDoc()} />);
    const view = within(container);

    const contactRow = view.getByText('ada@example.com').closest('div');
    expect(contactRow).not.toBeNull();
    expect(contactRow?.contains(view.getByText('London'))).toBe(false);
  });
});
