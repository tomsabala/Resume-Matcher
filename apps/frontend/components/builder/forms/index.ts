import type React from 'react';
import type { SectionKind } from '@/lib/types/document';
import { GenericTextForm } from './generic-text-form';
import { GenericItemForm } from './generic-item-form';
import { GenericListForm } from './generic-list-form';
import { GroupsForm } from './groups-form';
import type { SectionFormProps } from './types';

/**
 * The only mapping between a section's shape and its editor.
 *
 * `Record<SectionKind, …>` is exhaustive by construction: adding a kind to the
 * contract breaks this file until an editor exists for it.
 */
export const SECTION_KIND_FORMS: Record<SectionKind, React.FC<SectionFormProps>> = {
  text: GenericTextForm,
  entries: GenericItemForm,
  tags: GenericListForm,
  groups: GroupsForm,
};

export type { SectionFormProps };
