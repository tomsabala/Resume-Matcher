'use client';

import React from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import GripVertical from 'lucide-react/dist/esm/icons/grip-vertical';
import MoreVertical from 'lucide-react/dist/esm/icons/more-vertical';
import Layers from 'lucide-react/dist/esm/icons/layers';
import { Card } from '@/components/ui/card';
import { useTranslations } from '@/lib/i18n';
import type { Application } from '@/lib/api/tracker';

interface ApplicationCardProps {
  application: Application;
  selected: boolean;
  sharedResume: boolean;
  onToggleSelect: (id: string) => void;
  onOpen: (id: string) => void;
  /** Mobile replacement for cross-stage drag: opens the board-owned action sheet. */
  onRequestActions: (application: Application) => void;
}

export function ApplicationCard({
  application,
  selected,
  sharedResume,
  onToggleSelect,
  onOpen,
  onRequestActions,
}: ApplicationCardProps) {
  const { t } = useTranslations();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: application.application_id,
  });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const company = application.company?.trim();
  const role = application.role?.trim();

  return (
    <div ref={setNodeRef} style={style}>
      <Card
        variant="interactive"
        noPadding
        className={`p-3 border-ink shadow-sw-xs lg:border-transparent lg:shadow-none ${selected ? 'ring-2 ring-primary' : ''}`}
      >
        <div className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect(application.application_id)}
            onClick={(e) => e.stopPropagation()}
            aria-label={t('tracker.card.selectAria')}
            className="relative mt-1 h-4 w-4 shrink-0 cursor-pointer appearance-none border border-black bg-white before:absolute before:-inset-[14px] before:content-[''] checked:bg-black"
          />

          <button
            type="button"
            onClick={() => onOpen(application.application_id)}
            className="min-w-0 flex-1 text-left"
          >
            <p className="truncate text-sm font-semibold text-ink">
              {company || t('tracker.card.companyUnknown')}
            </p>
            <p className="truncate font-mono text-xs text-ink-soft">
              {role || t('tracker.card.roleUnknown')}
            </p>
            {application.applied_at && (
              <p className="mt-1 font-mono text-[10px] uppercase tracking-wide text-steel-grey">
                {new Date(application.applied_at).toLocaleDateString()}
              </p>
            )}
            {sharedResume && (
              <span className="mt-1 inline-flex items-center gap-1 border border-black bg-paper-tint px-1 font-mono text-[10px] uppercase text-ink-soft">
                <Layers className="h-3 w-3" />
                {t('tracker.card.sharedResume')}
              </span>
            )}
          </button>

          <button
            type="button"
            className="touch-none -m-2 mt-0 hidden h-11 w-11 shrink-0 cursor-grab items-center justify-center text-steel-grey hover:text-ink active:cursor-grabbing lg:flex"
            aria-label={t('tracker.card.dragAria')}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="h-4 w-4" />
          </button>

          <button
            type="button"
            className="-m-2 mt-0 flex h-11 w-11 shrink-0 items-center justify-center text-steel-grey lg:hidden"
            aria-label={t('common.more')}
            onClick={(e) => {
              e.stopPropagation();
              onRequestActions(application);
            }}
          >
            <MoreVertical className="h-4 w-4" />
          </button>
        </div>
      </Card>
    </div>
  );
}
