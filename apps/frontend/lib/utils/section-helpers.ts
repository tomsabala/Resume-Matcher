/**
 * Section helpers for the data-driven resume document (schema version 2).
 *
 * Sections are pure data: order is list order, the heading is free text and
 * the shape is `Section.kind`. Nothing here enumerates resume sections.
 */

import type { ResumeDocument, Section, SectionKind } from '@/lib/types/document';
import en from '@/messages/en.json';
import { getNestedValue } from '@/lib/i18n/utils';

/** Visible sections, in document order. */
export function visibleSections(doc: ResumeDocument): Section[] {
  return doc.sections.filter((section) => section.visible);
}

/** Every section including hidden ones, in document order (management UI). */
export function allSections(doc: ResumeDocument): Section[] {
  return doc.sections;
}

/**
 * A section key is referenced by AI change paths and diff paths, so it must be
 * unique within the document. Collisions get a numeric suffix (`_2`, `_3`, …).
 */
function uniqueKey(doc: ResumeDocument, heading: string): string {
  const base =
    heading
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'section';
  const taken = new Set(doc.sections.map((section) => section.key));
  if (!taken.has(base)) return base;

  let suffix = 2;
  while (taken.has(`${base}_${suffix}`)) suffix += 1;
  return `${base}_${suffix}`;
}

/** Build an empty section of `kind` whose key is unique within `doc`. */
export function createSection(doc: ResumeDocument, heading: string, kind: SectionKind): Section {
  return {
    id: crypto.randomUUID(),
    key: uniqueKey(doc, heading),
    heading,
    headingI18nKey: null,
    kind,
    visible: true,
    column: 'main',
    text: '',
    entries: [],
    tags: [],
    groups: [],
  };
}

/**
 * The heading to display.
 *
 * A section projected from a v1 built-in carries `headingI18nKey`. Its heading
 * is only a translatable label while it still equals that key's **English**
 * default — the moment the user edits it, the literal text wins. A user
 * heading must never be fed to `t()`: `Messages = typeof en` makes an unknown
 * key a build failure, and `getNestedValue` would echo the path back.
 */
export function sectionHeading(section: Section, t: (key: string) => string): string {
  const key = section.headingI18nKey;
  if (!key) return section.heading;

  const englishDefault = getNestedValue(en as unknown as Record<string, unknown>, key);
  if (englishDefault !== section.heading) return section.heading;

  return t(key);
}
