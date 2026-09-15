import type { Section } from '@/lib/types/document';

/**
 * Every section editor takes the whole section and returns the whole section.
 *
 * Nothing about the form is keyed on *which* section this is — the registry in
 * `./index` dispatches on `section.kind`, so a section the code has never seen
 * is editable the moment it exists in the document.
 */
export interface SectionFormProps {
  section: Section;
  onChange: (next: Section) => void;
}
