'use client';

import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import {
  ChevronUp,
  ChevronDown,
  Trash2,
  Eye,
  EyeOff,
  Pencil,
  Check,
  X,
  Columns2,
} from 'lucide-react';
import type { Section } from '@/lib/types/document';
import { sectionHeading } from '@/lib/utils/section-helpers';
import { useTranslations } from '@/lib/i18n';
import { cn } from '@/lib/utils';

interface SectionHeadingEditorProps {
  heading: string;
  onRename: (newHeading: string) => void;
  /** Called on commit, cancel and Escape — the caller owns the editing flag. */
  onDone: () => void;
  inputClassName?: string;
  className?: string;
}

/**
 * The inline rename field. Lives here because the desktop section header and the
 * mobile section-editor bar are the same flow — neither may re-implement it.
 */
export const SectionHeadingEditor: React.FC<SectionHeadingEditorProps> = ({
  heading,
  onRename,
  onDone,
  inputClassName,
  className,
}) => {
  const { t } = useTranslations();
  const [editedHeading, setEditedHeading] = useState(heading);

  const commit = () => {
    // Committing writes the literal text, which is exactly how a renamed
    // section stops resolving through its headingI18nKey.
    if (editedHeading.trim()) {
      onRename(editedHeading.trim());
    }
    onDone();
  };

  return (
    <div className={cn('flex items-center gap-1', className)}>
      <Input
        value={editedHeading}
        onChange={(e) => setEditedHeading(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            commit();
          } else if (e.key === 'Escape') {
            onDone();
          }
        }}
        className={cn(
          'h-9 w-full sm:w-48 rounded-none border-black font-serif text-lg font-bold',
          inputClassName
        )}
        autoFocus
      />
      <Button
        variant="ghost"
        size="icon"
        className="h-11 w-11 lg:h-8 lg:w-8 text-green-700 hover:text-green-800 hover:bg-green-50"
        onClick={commit}
        aria-label={t('common.save')}
        title={t('common.save')}
      >
        <Check className="w-4 h-4" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="h-11 w-11 lg:h-8 lg:w-8 text-steel-grey hover:text-ink-soft hover:bg-paper-tint"
        onClick={onDone}
        aria-label={t('common.cancel')}
        title={t('common.cancel')}
      >
        <X className="w-4 h-4" />
      </Button>
    </div>
  );
};

interface SectionHeaderProps {
  section: Section;
  onRename: (newHeading: string) => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onToggleVisibility: () => void;
  onToggleColumn: () => void;
  isFirst: boolean;
  isLast: boolean;
  children?: React.ReactNode;
}

/**
 * Controls shared by every section, whatever its kind:
 * heading rename, reorder, delete, visibility and column placement.
 *
 * There are no built-in sections any more, so there is no section this refuses
 * to delete and no "custom" badge to distinguish.
 */
export const SectionHeader: React.FC<SectionHeaderProps> = ({
  section,
  onRename,
  onDelete,
  onMoveUp,
  onMoveDown,
  onToggleVisibility,
  onToggleColumn,
  isFirst,
  isLast,
  children,
}) => {
  const { t } = useTranslations();
  const heading = sectionHeading(section, t);
  const [isEditing, setIsEditing] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const isHidden = !section.visible;

  return (
    <div
      className={`space-y-0 border p-4 sm:p-6 bg-white shadow-sw-default ${
        isHidden ? 'border-dashed border-steel-grey opacity-60' : 'border-black'
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-black pb-2 mb-4">
        <div className="flex items-center gap-2">
          {isEditing ? (
            <SectionHeadingEditor
              heading={heading}
              onRename={onRename}
              onDone={() => setIsEditing(false)}
            />
          ) : (
            <>
              <h3 className="font-serif text-xl font-bold">{heading}</h3>
              <Button
                variant="ghost"
                size="icon"
                // Visible 24×24 (matches the small inline pencil aesthetic
                // next to the section title), but the touch area is
                // extended to 44×44 via -inset-[10px] to meet WCAG 2.5.8.
                // The default Button overlay (-inset-1.5) only gives 36×36
                // for h-6 buttons; this override adds 4 more px per side.
                className="h-6 w-6 text-steel-grey hover:text-ink-soft before:-inset-[10px]"
                onClick={() => setIsEditing(true)}
                aria-label={t('builder.sectionHeader.renameSection')}
                title={t('builder.sectionHeader.renameSection')}
              >
                <Pencil className="w-3 h-3" />
              </Button>
              {section.column === 'side' && (
                <span className="font-mono text-[10px] uppercase tracking-wider text-steel-grey bg-paper-tint px-1.5 py-0.5 border border-paper-tint">
                  {t('builder.sectionHeader.sidebarTag')}
                </span>
              )}
              {isHidden && (
                <span className="font-mono text-[10px] uppercase tracking-wider text-orange-600 bg-white px-1.5 py-0.5 border border-orange-500">
                  {t('builder.sectionHeader.hiddenFromPdfTag')}
                </span>
              )}
            </>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Column placement. Single-column templates ignore it; two-column
              templates partition on it. */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-steel-grey hover:text-ink-soft"
            onClick={onToggleColumn}
            aria-label={
              section.column === 'side'
                ? t('builder.sectionHeader.moveToMain')
                : t('builder.sectionHeader.moveToSide')
            }
            aria-pressed={section.column === 'side'}
            title={
              section.column === 'side'
                ? t('builder.sectionHeader.moveToMain')
                : t('builder.sectionHeader.moveToSide')
            }
          >
            <Columns2 className="w-4 h-4" />
          </Button>

          {/* Visibility Toggle. The parent container already applies
              opacity-60 when hidden, which carries the visual "faded" cue for
              the hidden state. A conditional text color here would be
              redundant — just use steel-grey. */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-steel-grey"
            onClick={onToggleVisibility}
            aria-label={
              section.visible
                ? t('builder.sectionHeader.hideSection')
                : t('builder.sectionHeader.showSection')
            }
            aria-pressed={!section.visible}
            title={
              section.visible
                ? t('builder.sectionHeader.hideSection')
                : t('builder.sectionHeader.showSection')
            }
          >
            {section.visible ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-steel-grey hover:text-ink-soft disabled:opacity-30"
            onClick={onMoveUp}
            disabled={isFirst}
            aria-label={t('builder.sectionHeader.moveUp')}
            title={t('builder.sectionHeader.moveUp')}
          >
            <ChevronUp className="w-4 h-4" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-steel-grey hover:text-ink-soft disabled:opacity-30"
            onClick={onMoveDown}
            disabled={isLast}
            aria-label={t('builder.sectionHeader.moveDown')}
            title={t('builder.sectionHeader.moveDown')}
          >
            <ChevronDown className="w-4 h-4" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
            onClick={() => setShowDeleteConfirm(true)}
            aria-label={t('builder.sectionHeader.deleteSection')}
            title={t('builder.sectionHeader.deleteSection')}
          >
            <Trash2 className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {children}

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        title={t('builder.sectionHeader.deleteTitle')}
        description={t('builder.sectionHeader.deleteDescription', { name: heading })}
        confirmLabel={t('common.delete')}
        cancelLabel={t('common.cancel')}
        variant="danger"
        onConfirm={onDelete}
      />
    </div>
  );
};
