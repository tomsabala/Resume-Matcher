'use client';

import React from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { FileText, ChevronDown, ChevronRight } from 'lucide-react';
import { useTranslations } from '@/lib/i18n';
import type { RegenerateItemInput } from '@/lib/api/enrichment';

/**
 * One section's worth of regenerable content.
 *
 * The dialog no longer knows about "experience", "projects" and "skills": it
 * groups by whatever sections the document actually has, using their headings.
 */
export interface RegenerateGroup {
  key: string;
  heading: string;
  items: RegenerateItemInput[];
}

interface RegenerateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groups: RegenerateGroup[];
  selectedItems: RegenerateItemInput[];
  onSelectionChange: (items: RegenerateItemInput[]) => void;
  onContinue: () => void;
}

/**
 * RegenerateDialog Component
 *
 * First step of the regenerate wizard.
 * Allows user to select which resume items to regenerate.
 * Swiss International Style design.
 */
export const RegenerateDialog: React.FC<RegenerateDialogProps> = ({
  open,
  onOpenChange,
  groups,
  selectedItems,
  onSelectionChange,
  onContinue,
}) => {
  const { t } = useTranslations();
  // Collapsed-by-exception: a section is expanded unless the user closed it,
  // so a section that appears after this state was created is still visible.
  const [collapsedGroups, setCollapsedGroups] = React.useState<string[]>([]);

  const toggleGroup = (key: string) =>
    setCollapsedGroups((collapsed) =>
      collapsed.includes(key) ? collapsed.filter((item) => item !== key) : [...collapsed, key]
    );

  const isSelected = (item: RegenerateItemInput) =>
    selectedItems.some((s) => s.item_id === item.item_id);

  const toggleItem = (item: RegenerateItemInput) => {
    if (isSelected(item)) {
      onSelectionChange(selectedItems.filter((s) => s.item_id !== item.item_id));
    } else {
      onSelectionChange([...selectedItems, item]);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px] p-0 gap-0 rounded-none">
        <DialogHeader className="p-6 pb-4 border-b border-black">
          <DialogTitle className="font-serif text-xl font-bold uppercase tracking-tight">
            {t('builder.regenerate.selectDialog.title')}
          </DialogTitle>
          <DialogDescription className="font-mono text-xs text-ink-soft mt-2">
            {t('builder.regenerate.selectDialog.subtitle')}
          </DialogDescription>
        </DialogHeader>

        <div className="p-6 space-y-4 max-h-[50vh] overflow-y-auto">
          {groups.length === 0 && (
            <div className="text-center py-8 text-steel-grey font-mono text-sm">
              {t('builder.regenerate.selectDialog.noItemsAvailable')}
            </div>
          )}

          {groups.map((group) => {
            const isExpanded = !collapsedGroups.includes(group.key);

            return (
              <div key={group.key} className="border border-black">
                <button
                  type="button"
                  onClick={() => toggleGroup(group.key)}
                  aria-expanded={isExpanded}
                  className="w-full p-4 flex items-center justify-between bg-background hover:bg-secondary transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <FileText className="w-5 h-5" />
                    <span className="font-mono text-sm uppercase tracking-wider font-medium">
                      {group.heading}
                    </span>
                    <span className="font-mono text-xs text-steel-grey">
                      ({group.items.length})
                    </span>
                  </div>
                  {isExpanded ? (
                    <ChevronDown className="w-4 h-4" />
                  ) : (
                    <ChevronRight className="w-4 h-4" />
                  )}
                </button>
                {isExpanded && (
                  <div className="border-t border-black">
                    {group.items.map((item) => (
                      <ItemRow
                        key={item.item_id}
                        item={item}
                        isSelected={isSelected(item)}
                        onToggle={() => toggleItem(item)}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <DialogFooter className="p-4 bg-secondary border-t border-black flex-row justify-end gap-3">
          <DialogClose asChild>
            <Button variant="outline" className="rounded-none border-black">
              {t('common.cancel')}
            </Button>
          </DialogClose>
          <Button
            onClick={onContinue}
            disabled={selectedItems.length === 0}
            className="rounded-none"
          >
            {t('builder.regenerate.selectDialog.continueButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/**
 * ItemRow - Individual selectable item row
 */
interface ItemRowProps {
  item: RegenerateItemInput;
  isSelected: boolean;
  onToggle: () => void;
}

const ItemRow: React.FC<ItemRowProps> = ({ item, isSelected, onToggle }) => {
  const { t } = useTranslations();

  const contentCount = item.current_content.length;
  const itemCountKey =
    contentCount === 1
      ? 'builder.regenerate.selectDialog.itemCount.one'
      : 'builder.regenerate.selectDialog.itemCount.other';
  const itemCountLabel = t(itemCountKey).replace('{count}', String(contentCount));

  return (
    <button
      type="button"
      onClick={onToggle}
      className={`w-full p-4 flex items-center gap-4 text-left transition-colors ${
        isSelected ? 'bg-blue-50' : 'bg-white hover:bg-paper-tint'
      }`}
    >
      {/* Checkbox */}
      <div
        className={`w-5 h-5 border-2 flex items-center justify-center transition-colors ${
          isSelected ? 'border-blue-700 bg-blue-700' : 'border-black bg-white'
        }`}
      >
        {isSelected && (
          <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
          </svg>
        )}
      </div>

      {/* Item Info */}
      <div className="flex-1 min-w-0">
        <div className="font-sans font-medium text-sm truncate">{item.title}</div>
        {item.subtitle && (
          <div className="font-mono text-xs text-steel-grey truncate">{item.subtitle}</div>
        )}
      </div>

      {/* Content preview */}
      <div className="font-mono text-xs text-steel-grey">{itemCountLabel}</div>
    </button>
  );
};

export default RegenerateDialog;
