import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { LivePreview } from '@/components/resume-wizard/live-preview';
import { createInitialResumeWizardState } from '@/lib/api/resume-wizard';
import { makeDocument, makeEntry, makeSection } from './fixtures/document';

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key }),
}));

describe('LivePreview', () => {
  it('shows the empty state before any answers', () => {
    render(<LivePreview doc={createInitialResumeWizardState().resume_data} inferredSkills={[]} />);
    expect(screen.getByText('resumeWizard.preview.empty')).toBeInTheDocument();
  });

  it('renders name, experience and skills as content (not counts)', () => {
    const doc = makeDocument({
      header: { name: 'Priya Shah', headline: '', contacts: [] },
      sections: [
        makeSection({
          key: 'experience',
          kind: 'entries',
          heading: 'Experience',
          entries: [
            makeEntry({
              id: 'e1',
              title: 'Senior PM',
              subtitle: 'Acme',
              period: '2021',
              bullets: [{ text: 'Cut churn 18%', style: 'bullet' }],
            }),
          ],
        }),
        makeSection({
          key: 'skills',
          kind: 'tags',
          heading: 'Skills',
          tags: ['SQL', 'Roadmapping'],
        }),
      ],
    });

    render(<LivePreview doc={doc} inferredSkills={[]} />);

    expect(screen.getByText('Priya Shah')).toBeInTheDocument();
    expect(screen.getByText(/Senior PM/)).toBeInTheDocument();
    expect(screen.getByText('Cut churn 18%')).toBeInTheDocument();
    const region = screen.getByRole('complementary');
    expect(within(region).getByText('SQL')).toBeInTheDocument();
  });

  it('renders a section the build has never heard of, by its own heading', () => {
    const doc = makeDocument({
      header: { name: 'Priya Shah', headline: '', contacts: [] },
      sections: [
        makeSection({
          key: 'military_service',
          kind: 'text',
          heading: 'Military Service',
          text: 'Signals Officer, 2016-2019',
        }),
      ],
    });

    render(<LivePreview doc={doc} inferredSkills={[]} />);

    expect(screen.getByText('Military Service')).toBeInTheDocument();
    expect(screen.getByText('Signals Officer, 2016-2019')).toBeInTheDocument();
  });

  it('deduplicates inferred skills against values already written anywhere', () => {
    const doc = makeDocument({
      header: { name: 'Priya', headline: '', contacts: [] },
      sections: [
        makeSection({
          key: 'skills',
          kind: 'groups',
          heading: 'Skills',
          groups: [{ label: 'Technical Skills', values: ['React'] }],
        }),
      ],
    });

    render(<LivePreview doc={doc} inferredSkills={['react', 'Node.js']} />);

    expect(screen.getAllByText(/^react$/i)).toHaveLength(1);
    expect(screen.getByText('Node.js')).toBeInTheDocument();
  });
});
