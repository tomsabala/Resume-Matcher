/**
 * Shared `ResumeDocument` (schema version 2) fixtures.
 *
 * Tests that only need "a valid document the app considers meaningful" build
 * one here instead of repeating a large literal. Everything is a factory:
 * documents are mutated by the code under test, so every call must hand back a
 * fresh object graph.
 */

import type {
  Contact,
  Entry,
  Header,
  ResumeDocument,
  Section,
  SectionKind,
} from '@/lib/types/document';

export function makeContact(overrides: Partial<Contact> = {}): Contact {
  return {
    id: 'contact-1',
    kind: 'email',
    label: 'ada@example.com',
    value: 'ada@example.com',
    url: '',
    ...overrides,
  };
}

export function makeHeader(overrides: Partial<Header> = {}): Header {
  return {
    name: 'Ada Lovelace',
    headline: 'Analytical Engineer',
    contacts: [makeContact()],
    ...overrides,
  };
}

export function makeEntry(overrides: Partial<Entry> = {}): Entry {
  return {
    id: 'entry-1',
    title: 'Senior Software Engineer',
    subtitle: 'Analytical Engines Ltd',
    meta: 'London',
    period: '2020 - Present',
    links: [],
    summary: '',
    bullets: [{ text: 'Shipped the difference engine', style: 'bullet' }],
    ...overrides,
  };
}

/** A section of `kind`; the caller supplies the content field that kind reads. */
export function makeSection(
  overrides: Partial<Section> & { key: string; kind: SectionKind }
): Section {
  return {
    id: `section-${overrides.key}`,
    heading: overrides.key,
    headingI18nKey: null,
    visible: true,
    column: 'main',
    text: '',
    entries: [],
    tags: [],
    groups: [],
    ...overrides,
  };
}

/** A document with a header and whatever sections the caller passes. */
export function makeDocument(
  overrides: { header?: Partial<Header>; sections?: Section[] } = {}
): ResumeDocument {
  return {
    schemaVersion: 2,
    header: makeHeader(overrides.header),
    sections: overrides.sections ?? [],
  };
}

/**
 * A realistic document: a `text` summary, an `entries` experience section and
 * a `groups` skills section — the three shapes most UI paths touch.
 */
export function sampleDocument(
  overrides: { header?: Partial<Header>; summary?: string } = {}
): ResumeDocument {
  return makeDocument({
    header: overrides.header,
    sections: [
      makeSection({
        key: 'summary',
        kind: 'text',
        heading: 'Summary',
        headingI18nKey: 'resume.sections.summary',
        text: overrides.summary ?? 'Real summary from the server',
      }),
      makeSection({
        key: 'experience',
        kind: 'entries',
        heading: 'Experience',
        headingI18nKey: 'resume.sections.experience',
        entries: [makeEntry()],
      }),
      makeSection({
        key: 'skills',
        kind: 'groups',
        heading: 'Skills',
        headingI18nKey: 'resume.sections.skills',
        column: 'side',
        groups: [{ label: 'Technical Skills', values: ['TypeScript', 'Python'] }],
      }),
    ],
  });
}

/** A copy of `doc` whose `summary` section carries `text`. */
export function withSummary(doc: ResumeDocument, text: string): ResumeDocument {
  const sections = doc.sections.map((section) =>
    section.key === 'summary' ? { ...section, text } : section
  );
  if (!sections.some((section) => section.key === 'summary')) {
    sections.unshift(makeSection({ key: 'summary', kind: 'text', heading: 'Summary', text }));
  }
  return { ...doc, header: { ...doc.header }, sections };
}
