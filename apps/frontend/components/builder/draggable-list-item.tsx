'use client';

import React from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical } from 'lucide-react';
import { useTranslations } from '@/lib/i18n';

interface DraggableListItemProps {
  id: string;
  children: React.ReactNode;
}

/**
 * DraggableListItem Component
 *
 * Generic wrapper for list items (experience, education, projects, etc.) to make them draggable using @dnd-kit.
 * Provides:
 * - Drag handle (grip icon) for initiating drag operations
 * - Visual feedback during drag (opacity, cursor)
 * - Keyboard accessibility for drag operations
 * - Swiss International Style aesthetic (square corners, high contrast)
 */
export const DraggableListItem: React.FC<DraggableListItemProps> = ({ id, children }) => {
  const { t } = useTranslations();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} className="relative">
      {/* Below `lg` the handle is a 44px strip ABOVE the item, not a left
          gutter: a gutter would cost 44px of a 343px pane and leave a bullet
          field unusable. At `lg` it is the same 16px left rail as before. */}
      <div
        {...attributes}
        {...listeners}
        className="touch-none absolute left-0 top-0 h-11 w-11 flex items-center justify-center cursor-grab active:cursor-grabbing z-10 lg:h-full lg:w-4 lg:items-start lg:pt-0"
        aria-label={t('common.dragToReorder')}
        title={t('common.dragToReorder')}
      >
        <GripVertical className="w-4 h-4 text-steel-grey hover:text-ink-soft transition-colors" />
      </div>

      {/* List Item Content - offset to clear the drag handle */}
      <div className="pt-11 lg:pt-0 lg:pl-4">{children}</div>
    </div>
  );
};
