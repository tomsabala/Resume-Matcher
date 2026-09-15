import { describe, expect, it } from 'vitest';
import { hasMeaningfulResumeContent } from '@/lib/utils/resume-content';

/**
 * Guards the frontend half of a predicate that is mirrored from
 * `apps/backend/app/services/parser.py::has_meaningful_resume_content`.
 * The dashboard downgrades a `ready` resume with no meaningful content to
 * `failed`, so a false positive here means users get a blank PDF instead of a
 * retry prompt.
 */

describe('hasMeaningfulResumeContent', () => {
  it('rejects non-object input', () => {
    expect(hasMeaningfulResumeContent(null)).toBe(false);
    expect(hasMeaningfulResumeContent(undefined)).toBe(false);
    expect(hasMeaningfulResumeContent('resume')).toBe(false);
    expect(hasMeaningfulResumeContent(42)).toBe(false);
    // A top-level array is not a ResumeDocument even when it holds text.
    expect(hasMeaningfulResumeContent([{ header: { name: 'Ada' } }])).toBe(false);
  });

  it('rejects the empty document an LLM can return and still validate', () => {
    expect(hasMeaningfulResumeContent({})).toBe(false);
    expect(
      hasMeaningfulResumeContent({
        schemaVersion: 2,
        header: { name: '', headline: '', contacts: [] },
        sections: [],
      })
    ).toBe(false);
  });

  it('accepts a header that carries a name', () => {
    expect(hasMeaningfulResumeContent({ header: { name: 'Ada Lovelace' }, sections: [] })).toBe(
      true
    );
    expect(hasMeaningfulResumeContent({ header: { name: '   ' }, sections: [] })).toBe(false);
  });

  it('reads only the field group the section kind renders', () => {
    const base = { id: 's1', key: 'extra', heading: 'Extra', visible: true };
    // Content parked in the wrong field group never renders, so it is not content.
    expect(
      hasMeaningfulResumeContent({
        sections: [{ ...base, kind: 'entries', text: 'orphaned prose', entries: [] }],
      })
    ).toBe(false);
    expect(
      hasMeaningfulResumeContent({ sections: [{ ...base, kind: 'text', text: 'Real prose' }] })
    ).toBe(true);
    expect(
      hasMeaningfulResumeContent({ sections: [{ ...base, kind: 'tags', tags: ['', '  '] }] })
    ).toBe(false);
    expect(
      hasMeaningfulResumeContent({ sections: [{ ...base, kind: 'tags', tags: ['TypeScript'] }] })
    ).toBe(true);
    expect(
      hasMeaningfulResumeContent({
        sections: [{ ...base, kind: 'groups', groups: [{ label: '', values: [] }] }],
      })
    ).toBe(false);
    expect(
      hasMeaningfulResumeContent({
        sections: [{ ...base, kind: 'groups', groups: [{ label: '', values: ['Spanish'] }] }],
      })
    ).toBe(true);
  });

  it('accepts an entry whose only content is a bullet', () => {
    const section = {
      id: 's1',
      key: 'work',
      heading: 'Experience',
      visible: true,
      kind: 'entries',
    };
    expect(
      hasMeaningfulResumeContent({
        sections: [
          {
            ...section,
            entries: [
              {
                id: 'e1',
                title: '',
                subtitle: '',
                bullets: [{ text: 'Shipped it', style: 'bullet' }],
              },
            ],
          },
        ],
      })
    ).toBe(true);
    expect(
      hasMeaningfulResumeContent({
        sections: [{ ...section, entries: [{ id: 'e1', title: '', bullets: [{ text: '  ' }] }] }],
      })
    ).toBe(false);
  });

  it('ignores hidden sections: they never reach the PDF', () => {
    expect(
      hasMeaningfulResumeContent({
        header: { name: '' },
        sections: [
          { id: 's1', key: 'summary', kind: 'text', visible: false, text: 'Hidden prose' },
        ],
      })
    ).toBe(false);
  });

  it('rejects an unknown section kind instead of guessing a field group', () => {
    expect(
      hasMeaningfulResumeContent({
        sections: [{ id: 's1', key: 'x', kind: 'timeline', text: 'Prose', tags: ['a'] }],
      })
    ).toBe(false);
  });
});
