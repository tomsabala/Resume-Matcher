/**
 * The resume document contract (schema version 2).
 *
 * Mirror of `apps/backend/app/schemas/document.py`. This is the **single**
 * home for resume shape types on the frontend — components import from here,
 * never redeclare.
 *
 * Sections, their headings, their order and their shapes are data. No
 * component enumerates resume sections; renderers and editors dispatch on
 * `SectionKind` through the registries in `components/resume/section-kinds`
 * and `components/builder/forms`.
 */

export const SCHEMA_VERSION = 2 as const;

/** The shape of a section's content. */
export type SectionKind = 'text' | 'entries' | 'tags' | 'groups';

export interface Bullet {
  text: string;
  /** `plain` renders the row as a paragraph, without a bullet marker. */
  style: 'bullet' | 'plain';
}

export interface EntryLink {
  kind: 'github' | 'website' | 'linkedin' | 'other';
  url: string;
}

/**
 * One row of an `entries` section. Field names are generic on purpose:
 * `title`/`subtitle` are job title/company, institution/degree, project
 * name/role, or military role/unit depending on the section.
 */
export interface Entry {
  id: string;
  title: string;
  subtitle: string;
  /** Location or other free metadata. */
  meta: string;
  /** Stored verbatim, never parsed. */
  period: string;
  links: EntryLink[];
  /** The paragraph above the bullets. */
  summary: string;
  bullets: Bullet[];
}

export interface TagGroup {
  label: string;
  values: string[];
}

export interface Section {
  id: string;
  /** Slug, unique per document; used in AI change paths and diff paths. */
  key: string;
  /** User-authored headline, free text. */
  heading: string;
  /**
   * Set only on sections projected from the v1 built-ins. Render the
   * translation only while `heading` still equals that key's English default
   * — a user heading must never become a translation key, because
   * `Messages = typeof en` turns a missing key into a build failure.
   */
  headingI18nKey?: string | null;
  kind: SectionKind;
  visible: boolean;
  /** Two-column templates partition on this. */
  column: 'main' | 'side';
  text: string;
  entries: Entry[];
  tags: string[];
  groups: TagGroup[];
}

export type ContactKind =
  'email' | 'phone' | 'website' | 'github' | 'linkedin' | 'location' | 'other';

export interface Contact {
  id: string;
  kind: ContactKind;
  /** Displayed text; empty renders icon-only. */
  label: string;
  value: string;
  /** Empty means derive from `kind` + `value`. */
  url: string;
}

export interface Header {
  name: string;
  headline: string;
  contacts: Contact[];
}

export interface ResumeDocument {
  schemaVersion: 2;
  header: Header;
  sections: Section[];
}

export function emptyHeader(): Header {
  return { name: '', headline: '', contacts: [] };
}

export function emptyDocument(): ResumeDocument {
  return { schemaVersion: SCHEMA_VERSION, header: emptyHeader(), sections: [] };
}
