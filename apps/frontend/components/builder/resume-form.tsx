'use client';

import React, { useState } from 'react';
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
import { ChevronLeft, ChevronRight, MoreVertical, Sliders } from 'lucide-react';
import type { Header, ResumeDocument, Section, SectionKind } from '@/lib/types/document';
import { PersonalInfoForm } from './forms/personal-info-form';
import { SECTION_KIND_FORMS } from './forms';
import { SectionHeader, SectionHeadingEditor } from './section-header';
import { AddSectionButton } from './add-section-dialog';
import { DraggableSectionWrapper } from './draggable-section-wrapper';
import { createSection, sectionHeading } from '@/lib/utils/section-helpers';
import { Button } from '@/components/ui/button';
import { ListRow } from '@/components/ui/list-row';
import { ActionSheet, type ActionSheetItem } from '@/components/ui/action-sheet';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { useIsMobile } from '@/hooks/use-is-mobile';
import { useTranslations } from '@/lib/i18n';

interface ResumeFormProps {
  doc: ResumeDocument;
  onUpdate: (doc: ResumeDocument) => void;
  /**
   * Opens the formatting sheet. On a phone the formatting panel is not inline
   * chrome above the first field — it is one row in the section index.
   */
  onOpenFormatting: () => void;
}

/** The section index's pseudo-id for the document header. */
const HEADER_SECTION_ID = '__header__';

/**
 * The resume editor.
 *
 * Section order is list order, the editor for a section is looked up by its
 * `kind`, and the header is edited outside the section list. Nothing here
 * mentions a section by name, so a section this build has never seen is fully
 * editable the moment the document contains it.
 *
 * Below `lg` the flat tree becomes a two-level drill-down: an index of section
 * rows, then one section's fields alone. The index renders no drag gutter
 * unless reorder mode is on, and the section editor renders neither the gutter
 * nor the `SectionHeader` card — that is what takes a bullet field from 147px
 * to 311px at 375px.
 */
export const ResumeForm: React.FC<ResumeFormProps> = ({ doc, onUpdate, onOpenFormatting }) => {
  const { t } = useTranslations();
  const isMobile = useIsMobile();
  const [openSectionId, setOpenSectionId] = useState<string | null>(null);
  const [reorderMode, setReorderMode] = useState(false);
  const [isRenaming, setIsRenaming] = useState(false);
  const [sectionSheetOpen, setSectionSheetOpen] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

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

  const sectionIds = sections.map((section) => section.id);

  const desktopTree = (
    <DndContext
      id="resume-sections"
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={sectionIds} strategy={verticalListSortingStrategy}>
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

  // The section whose editor is open, or null while the index is showing. An id
  // left behind by a deleted section falls back to the index on its own.
  const openSection =
    openSectionId && openSectionId !== HEADER_SECTION_ID
      ? (sections.find((section) => section.id === openSectionId) ?? null)
      : null;
  const headerIsOpen = openSectionId === HEADER_SECTION_ID;

  /** Only `entries` and `groups` sections have a countable item list. */
  const itemCount = (section: Section): number | null => {
    if (section.kind === 'entries') return section.entries.length;
    if (section.kind === 'groups') return section.groups.length;
    return null;
  };

  const sectionBadges = (section: Section): React.ReactNode => {
    if (section.column !== 'side' && section.visible) return undefined;
    return (
      <>
        {section.column === 'side' && (
          <span className="border border-paper-tint bg-paper-tint px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-steel-grey">
            {t('builder.sectionHeader.sidebarTag')}
          </span>
        )}
        {!section.visible && (
          <span className="border border-orange-500 bg-white px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-orange-600">
            {t('builder.sectionHeader.hiddenFromPdfTag')}
          </span>
        )}
      </>
    );
  };

  const sectionRow = (section: Section) => {
    const count = itemCount(section);
    return (
      <ListRow
        key={section.id}
        title={sectionHeading(section, t)}
        subtitle={count === null ? undefined : t('builder.sections.itemCount', { count })}
        meta={sectionBadges(section)}
        // Reorder mode hands the row to the drag handle: a tap that both
        // reorders and navigates is neither.
        onClick={reorderMode ? undefined : () => setOpenSectionId(section.id)}
        trailing={reorderMode ? undefined : <ChevronRight className="h-5 w-5" aria-hidden="true" />}
      />
    );
  };

  const sectionIndex = (
    <>
      <ListRow
        leading={<Sliders className="h-5 w-5" />}
        title={t('builder.formatting.panelTitle')}
        onClick={onOpenFormatting}
        trailing={<ChevronRight className="h-5 w-5" aria-hidden="true" />}
      />
      <ListRow
        title={t('builder.header.title')}
        subtitle={doc.header.name || undefined}
        onClick={() => setOpenSectionId(HEADER_SECTION_ID)}
        trailing={<ChevronRight className="h-5 w-5" aria-hidden="true" />}
      />

      <div className="flex items-center justify-between border-b border-black px-4 py-2">
        <span className="font-mono text-xs font-bold uppercase tracking-wider">
          {t('builder.sections.title')}
        </span>
        <Button variant="outline" size="sm" onClick={() => setReorderMode((value) => !value)}>
          {reorderMode ? t('common.finish') : t('builder.sections.reorder')}
        </Button>
      </div>

      {reorderMode ? (
        <DndContext
          id="resume-sections-mobile"
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext items={sectionIds} strategy={verticalListSortingStrategy}>
            {sections.map((section) => (
              <DraggableSectionWrapper key={section.id} id={section.id}>
                {sectionRow(section)}
              </DraggableSectionWrapper>
            ))}
          </SortableContext>
        </DndContext>
      ) : (
        sections.map((section) => sectionRow(section))
      )}

      <div className="p-4">
        <AddSectionButton onAdd={handleAddSection} />
      </div>
    </>
  );

  const sectionEditor = (section: Section) => {
    const SectionForm = SECTION_KIND_FORMS[section.kind];
    const heading = sectionHeading(section, t);
    const index = sections.findIndex((item) => item.id === section.id);

    const items: ActionSheetItem[] = [
      {
        id: 'rename',
        label: t('builder.sectionHeader.renameSection'),
        onSelect: () => setIsRenaming(true),
      },
      {
        id: 'visibility',
        label: section.visible
          ? t('builder.sectionHeader.hideSection')
          : t('builder.sectionHeader.showSection'),
        onSelect: () => patchSection(section.id, { visible: !section.visible }),
      },
      {
        id: 'column',
        label:
          section.column === 'side'
            ? t('builder.sectionHeader.moveToMain')
            : t('builder.sectionHeader.moveToSide'),
        onSelect: () =>
          patchSection(section.id, { column: section.column === 'side' ? 'main' : 'side' }),
      },
      {
        id: 'move-up',
        label: t('builder.sectionHeader.moveUp'),
        disabled: index <= 0,
        onSelect: () => moveSection(section.id, -1),
      },
      {
        id: 'move-down',
        label: t('builder.sectionHeader.moveDown'),
        disabled: index === sections.length - 1,
        onSelect: () => moveSection(section.id, 1),
      },
      {
        id: 'delete',
        label: t('builder.sectionHeader.deleteSection'),
        destructive: true,
        onSelect: () => setShowDeleteConfirm(true),
      },
    ];

    return (
      <>
        <div className="flex items-center gap-2 border-b border-black px-2 py-2">
          <button
            type="button"
            onClick={() => {
              setIsRenaming(false);
              setOpenSectionId(null);
            }}
            aria-label={t('common.back')}
            className="flex h-11 w-11 shrink-0 items-center justify-center"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          {isRenaming ? (
            <SectionHeadingEditor
              className="min-w-0 flex-1"
              inputClassName="sm:w-full"
              heading={heading}
              onRename={(next) => patchSection(section.id, { heading: next })}
              onDone={() => setIsRenaming(false)}
            />
          ) : (
            <span className="min-w-0 flex-1 truncate font-serif text-lg font-bold">{heading}</span>
          )}
          <button
            type="button"
            onClick={() => setSectionSheetOpen(true)}
            aria-label={t('common.more')}
            className="flex h-11 w-11 shrink-0 items-center justify-center"
          >
            <MoreVertical className="h-5 w-5" />
          </button>
        </div>

        {/* No DraggableSectionWrapper and no SectionHeader card: the fields get
            the whole pane width. */}
        <div className="p-4">
          <SectionForm section={section} onChange={(next) => updateSection(section.id, next)} />
        </div>

        <ActionSheet
          open={sectionSheetOpen}
          onOpenChange={setSectionSheetOpen}
          title={heading}
          items={items}
        />

        <ConfirmDialog
          open={showDeleteConfirm}
          onOpenChange={setShowDeleteConfirm}
          title={t('builder.sectionHeader.deleteTitle')}
          description={t('builder.sectionHeader.deleteDescription', { name: heading })}
          confirmLabel={t('common.delete')}
          cancelLabel={t('common.cancel')}
          variant="danger"
          onConfirm={() => {
            replaceSections(sections.filter((item) => item.id !== section.id));
            setOpenSectionId(null);
          }}
        />
      </>
    );
  };

  return (
    <>
      {/* Two entirely different trees: the runtime check unmounts the one that
          does not apply, and the CSS gate covers the first hydration frame —
          which reports desktop on a phone and must paint nothing. */}
      {!isMobile && <div className="hidden lg:block">{desktopTree}</div>}

      {isMobile && (
        <div className="-mx-4 border-t border-black md:-mx-8 lg:hidden">
          {headerIsOpen ? (
            <>
              <div className="flex items-center gap-2 border-b border-black px-2 py-2">
                <button
                  type="button"
                  onClick={() => setOpenSectionId(null)}
                  aria-label={t('common.back')}
                  className="flex h-11 w-11 shrink-0 items-center justify-center"
                >
                  <ChevronLeft className="h-5 w-5" />
                </button>
                <span className="min-w-0 flex-1 truncate font-serif text-lg font-bold">
                  {t('builder.header.title')}
                </span>
              </div>
              <div className="p-4">
                <PersonalInfoForm header={doc.header} onChange={handleHeaderChange} />
              </div>
            </>
          ) : openSection ? (
            sectionEditor(openSection)
          ) : (
            sectionIndex
          )}
        </div>
      )}
    </>
  );
};
