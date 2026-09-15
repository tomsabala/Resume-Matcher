import type {
  Bullet,
  Contact,
  Entry,
  EntryLink,
  ResumeDocument,
  Section,
  TagGroup,
} from '@/lib/types/document';

// Every parameter here is `unknown`: this runs against persisted documents that
// TypeScript never validated, so a null element or a truthy non-array is a real
// possibility and a narrow signature would only hide it.
const isMeaningfulText = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0;

const isObjectRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const normalizeTags = (value: unknown): string[] =>
  asArray(value)
    .filter(isMeaningfulText)
    .map((tag) => tag.trim());

const normalizeBullets = (value: unknown): Bullet[] =>
  asArray(value).flatMap((row) => {
    if (!isObjectRecord(row) || !isMeaningfulText(row.text)) return [];
    // Style is a property of the bullet, so it can no longer drift out of
    // alignment when a blank row is dropped — that was the whole point of
    // retiring the parallel `descriptionStyles` array.
    return [{ text: row.text.trim(), style: row.style === 'plain' ? 'plain' : 'bullet' }];
  });

const normalizeLinks = (value: unknown): EntryLink[] =>
  asArray(value).flatMap((link) => {
    if (!isObjectRecord(link) || !isMeaningfulText(link.url)) return [];
    const kind = link.kind;
    return [
      {
        kind:
          kind === 'github' || kind === 'website' || kind === 'linkedin'
            ? kind
            : ('other' as const),
        url: link.url.trim(),
      },
    ];
  });

const normalizeEntries = (value: unknown): Entry[] =>
  asArray(value).flatMap((raw) => {
    if (!isObjectRecord(raw)) return [];
    const entry: Entry = {
      id: isMeaningfulText(raw.id) ? raw.id : crypto.randomUUID(),
      title: isMeaningfulText(raw.title) ? raw.title.trim() : '',
      subtitle: isMeaningfulText(raw.subtitle) ? raw.subtitle.trim() : '',
      meta: isMeaningfulText(raw.meta) ? raw.meta.trim() : '',
      period: isMeaningfulText(raw.period) ? raw.period.trim() : '',
      links: normalizeLinks(raw.links),
      summary: isMeaningfulText(raw.summary) ? raw.summary.trim() : '',
      bullets: normalizeBullets(raw.bullets),
    };

    const isEmpty =
      !entry.title &&
      !entry.subtitle &&
      !entry.meta &&
      !entry.period &&
      !entry.summary &&
      entry.links.length === 0 &&
      entry.bullets.length === 0;
    return isEmpty ? [] : [entry];
  });

const normalizeGroups = (value: unknown): TagGroup[] =>
  asArray(value).flatMap((raw) => {
    if (!isObjectRecord(raw)) return [];
    const label = isMeaningfulText(raw.label) ? raw.label.trim() : '';
    const values = normalizeTags(raw.values);
    return !label && values.length === 0 ? [] : [{ label, values }];
  });

const normalizeContacts = (value: unknown): Contact[] =>
  asArray(value).flatMap((raw) => {
    if (!isObjectRecord(raw)) return [];
    const contact: Contact = {
      id: isMeaningfulText(raw.id) ? raw.id : crypto.randomUUID(),
      kind: (isMeaningfulText(raw.kind) ? raw.kind : 'other') as Contact['kind'],
      label: isMeaningfulText(raw.label) ? raw.label.trim() : '',
      value: isMeaningfulText(raw.value) ? raw.value.trim() : '',
      url: isMeaningfulText(raw.url) ? raw.url.trim() : '',
    };
    return !contact.value && !contact.label && !contact.url ? [] : [contact];
  });

/**
 * Drop content the user cannot see, without touching section identity.
 *
 * Blank rows are an editing artefact (an "add bullet" click the user never
 * filled in); they must not reach the PDF. Sections themselves are never
 * dropped: an empty section is a deliberate placeholder, and its key is
 * referenced by AI change paths.
 */
export const normalizeResumeForSave = (doc: ResumeDocument): ResumeDocument => ({
  ...doc,
  header: {
    name: doc.header?.name ?? '',
    headline: doc.header?.headline ?? '',
    contacts: normalizeContacts(doc.header?.contacts),
  },
  sections: asArray(doc.sections)
    .filter(isObjectRecord)
    .map((raw): Section => {
      const section = raw as unknown as Section;
      return {
        ...section,
        text: typeof section.text === 'string' ? section.text : '',
        entries: normalizeEntries(section.entries),
        tags: normalizeTags(section.tags),
        groups: normalizeGroups(section.groups),
      };
    }),
});

export const normalizeResumeForRender = normalizeResumeForSave;
