import type { Section } from '@/lib/types/document';

/**
 * Drop blank/whitespace-only strings so empty lines left over from editing
 * never reach the resume or the PDF (issue #763).
 */
export function nonBlank(values: readonly string[]): string[] {
  return values.filter((value) => value.trim() !== '');
}

/** Reads only the field group the section's kind renders. */
export function sectionHasContent(section: Section): boolean {
  switch (section.kind) {
    case 'text':
      return section.text.trim() !== '';
    case 'entries':
      return section.entries.length > 0;
    case 'tags':
      return nonBlank(section.tags).length > 0;
    case 'groups':
      return section.groups.some((group) => nonBlank(group.values).length > 0);
  }
}
