'use client';

import React from 'react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import type { Header, ResumeDocument, Section, SectionKind } from '@/lib/types/document';
import { PersonalInfoForm } from './forms/personal-info-form';
import { SECTION_KIND_FORMS } from './forms';
import { SectionHeader } from './section-header';
import { AddSectionButton } from './add-section-dialog';
import { DraggableSectionWrapper } from './draggable-section-wrapper';
import { createSection } from '@/lib/utils/section-helpers';

interface ResumeFormProps {
  doc: ResumeDocument;
  onUpdate: (doc: ResumeDocument) => void;
}

/**
 * The resume editor.
 *
 * Section order is list order, the editor for a section is looked up by its
 * `kind`, and the header is edited outside the section list. Nothing here
 * mentions a section by name, so a section this build has never seen is fully
 * editable the moment the document contains it.
 */
export const ResumeForm: React.FC<ResumeFormProps> = ({ doc, onUpdate }) => {
  const sections = doc.sections;

  const replaceSections = (next: Section[]) => onUpdate({ ...doc, sections: next });

  const updateSection = (id: string, next: Section) =>
    replaceSections(sections.map((section) => (section.id === id ? next : section)));

  const patchSection = (id: string, patch: Partial<Section>) =>
    replaceSections(
      sections.map((section) => (section.id === id ? { ...section, ...patch } : section))
    );

  const moveSection = (id: string, offset: number) => {
    const index = sections.findIndex((section) => section.id === id);
    const target = index + offset;
    if (index === -1 || target < 0 || target >= sections.length) return;
    replaceSections(arrayMove(sections, index, target));
  };

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = sections.findIndex((section) => section.id === active.id);
    const newIndex = sections.findIndex((section) => section.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    // Order is the array order: a reorder is an array move, with nothing to
    // renumber afterwards.
    replaceSections(arrayMove(sections, oldIndex, newIndex));
  };

  const handleAddSection = (heading: string, kind: SectionKind) =>
    replaceSections([...sections, createSection(doc, heading, kind)]);

  const handleHeaderChange = (header: Header) => onUpdate({ ...doc, header });

  return (
    <DndContext
      id="resume-sections"
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext
        items={sections.map((section) => section.id)}
        strategy={verticalListSortingStrategy}
      >
        <div className="space-y-6 pb-20">
          <PersonalInfoForm header={doc.header} onChange={handleHeaderChange} />

          {sections.map((section, index) => {
            const SectionForm = SECTION_KIND_FORMS[section.kind];

            return (
              <DraggableSectionWrapper key={section.id} id={section.id}>
                <SectionHeader
                  section={section}
                  onRename={(heading) => patchSection(section.id, { heading })}
                  onDelete={() =>
                    replaceSections(sections.filter((item) => item.id !== section.id))
                  }
                  onMoveUp={() => moveSection(section.id, -1)}
                  onMoveDown={() => moveSection(section.id, 1)}
                  onToggleVisibility={() => patchSection(section.id, { visible: !section.visible })}
                  onToggleColumn={() =>
                    patchSection(section.id, {
                      column: section.column === 'side' ? 'main' : 'side',
                    })
                  }
                  isFirst={index === 0}
                  isLast={index === sections.length - 1}
                >
                  <SectionForm
                    section={section}
                    onChange={(next) => updateSection(section.id, next)}
                  />
                </SectionHeader>
              </DraggableSectionWrapper>
            );
          })}

          <AddSectionButton onAdd={handleAddSection} />
        </div>
      </SortableContext>
    </DndContext>
  );
};
