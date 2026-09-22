'use client';

import * as React from 'react';

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './dialog';
import { cn } from '@/lib/utils';

export interface ActionSheetItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  destructive?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

export interface ActionSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  items: ActionSheetItem[];
}

/**
 * The replacement for crowded icon clusters on touch surfaces: one 56px-tall row per
 * action, anchored to the bottom edge by `Dialog`'s sheet presentation.
 */
export const ActionSheet: React.FC<ActionSheetProps> = ({
  open,
  onOpenChange,
  title,
  description,
  items,
}) => (
  <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="p-0 gap-0 sm:max-w-sm">
      <DialogHeader className="border-b border-black px-4 py-3 pr-14">
        <DialogTitle className="truncate font-serif text-base font-bold">{title}</DialogTitle>
        {description ? (
          <DialogDescription className="truncate font-mono text-xs uppercase tracking-wide">
            {description}
          </DialogDescription>
        ) : null}
      </DialogHeader>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          disabled={item.disabled}
          onClick={() => {
            // `onSelect` first: a handler that opens another sheet must win over the close.
            item.onSelect();
            onOpenChange(false);
          }}
          className={cn(
            'flex min-h-14 w-full items-center gap-3 border-b border-black px-4 text-left font-mono text-sm uppercase tracking-wide last:border-b-0 active:bg-secondary disabled:opacity-40',
            item.destructive && 'text-destructive'
          )}
        >
          {item.icon ? <span className="shrink-0">{item.icon}</span> : null}
          <span className="min-w-0 flex-1 truncate">{item.label}</span>
        </button>
      ))}
    </DialogContent>
  </Dialog>
);
