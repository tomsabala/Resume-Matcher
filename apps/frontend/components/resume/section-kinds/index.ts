import type React from 'react';
import type { Section, SectionKind } from '@/lib/types/document';
import { TextSection } from './text-section';
import { EntriesSection } from './entries-section';
import { TagsSection } from './tags-section';
import { GroupsSection } from './groups-section';

/**
 * The only place in the frontend that maps a section shape to markup.
 *
 * Templates never enumerate sections: they walk `doc.sections` and dispatch on
 * `section.kind` through this registry, so a section with a key no component
 * has ever heard of renders in all seven templates with no code change.
 */
export const SECTION_KIND_RENDERERS: Record<SectionKind, React.FC<{ section: Section }>> = {
  text: TextSection,
  entries: EntriesSection,
  tags: TagsSection,
  groups: GroupsSection,
};

export { TextSection, EntriesSection, TagsSection, GroupsSection };
export { sectionHasContent, nonBlank } from './content';
