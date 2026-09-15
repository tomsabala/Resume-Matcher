/**
 * Mirror of `apps/backend/app/services/parser.py::has_meaningful_resume_content`,
 * which is the authoritative implementation. The backend rejects an LLM parse
 * whose result carries no user-visible content; the dashboard uses the same
 * predicate to surface a legacy `ready` resume that stored an empty document as
 * `failed` instead of rendering a blank PDF.
 *
 * THE TWO COPIES MUST BE CHANGED TOGETHER.
 *
 * The rule: a `ResumeDocument` is meaningful when the header carries a name, or
 * when any *visible* section carries non-empty content **for its own kind**. A
 * hidden section never reaches the PDF, and a section only ever renders the
 * field group its `kind` selects — so a stray `text` on an `entries` section is
 * not content.
 */

import type { SectionKind } from '@/lib/types/document';

const isMeaningfulText = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0;

const isObjectRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const hasEntryContent = (value: unknown): boolean => {
  if (!isObjectRecord(value)) return false;
  return (
    isMeaningfulText(value.title) ||
    isMeaningfulText(value.subtitle) ||
    isMeaningfulText(value.meta) ||
    isMeaningfulText(value.period) ||
    isMeaningfulText(value.summary) ||
    asArray(value.bullets).some((row) => isObjectRecord(row) && isMeaningfulText(row.text)) ||
    asArray(value.links).some((link) => isObjectRecord(link) && isMeaningfulText(link.url))
  );
};

const hasGroupContent = (value: unknown): boolean => {
  if (!isObjectRecord(value)) return false;
  return isMeaningfulText(value.label) || asArray(value.values).some(isMeaningfulText);
};

/** Content test for the one field group a section's `kind` actually renders. */
const hasSectionContent = (section: Record<string, unknown>): boolean => {
  switch (section.kind as SectionKind) {
    case 'text':
      return isMeaningfulText(section.text);
    case 'entries':
      return asArray(section.entries).some(hasEntryContent);
    case 'tags':
      return asArray(section.tags).some(isMeaningfulText);
    case 'groups':
      return asArray(section.groups).some(hasGroupContent);
    default:
      return false;
  }
};

/**
 * Return whether a parsed resume document contains any user-facing content.
 *
 * `ResumeDocument` intentionally defaults every field to an empty string/list.
 * That is useful for the builder, but it also means an LLM response such as
 * `{"schemaVersion": 2, "header": {}, "sections": []}` validates successfully —
 * which would render a blank resume.
 */
export const hasMeaningfulResumeContent = (value: unknown): boolean => {
  if (!isObjectRecord(value)) return false;

  const header = value.header;
  if (isObjectRecord(header) && isMeaningfulText(header.name)) return true;

  return asArray(value.sections).some(
    (section) => isObjectRecord(section) && section.visible !== false && hasSectionContent(section)
  );
};
