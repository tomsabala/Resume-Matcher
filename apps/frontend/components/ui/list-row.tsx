'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

export interface ListRowProps {
  /** 40x40 monogram / icon block. */
  leading?: React.ReactNode;
  title: string;
  subtitle?: string;
  /** Badge(s) rendered under the subtitle. */
  meta?: React.ReactNode;
  /** Chevron, or an action button. */
  trailing?: React.ReactNode;
  selected?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  className?: string;
}

/**
 * The replacement for aspect-square cards on touch surfaces. No `hover:` styling —
 * hover never fires on touch, which is why the interactive card reads as flat on a phone.
 */
export const ListRow: React.FC<ListRowProps> = ({
  leading,
  title,
  subtitle,
  meta,
  trailing,
  selected = false,
  disabled = false,
  onClick,
  className,
}) => {
  // `trailing` is a sibling of the tappable area, never a child of it: it usually
  // holds its own button, and a button inside a button is invalid HTML that React
  // reports as a hydration error.
  const rowClassName = cn(
    'flex min-h-[4.5rem] w-full items-stretch border-b border-black bg-background',
    selected && 'bg-secondary',
    className
  );

  const contentClassName =
    'flex min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left disabled:opacity-50';

  const content = (
    <>
      {leading ? <span className="shrink-0">{leading}</span> : null}
      <span className="min-w-0 flex-1">
        <span className="block truncate font-serif text-base font-bold leading-tight">{title}</span>
        {subtitle ? (
          <span className="block truncate font-mono text-xs uppercase tracking-wide text-ink-soft">
            {subtitle}
          </span>
        ) : null}
        {meta ? <span className="mt-1 flex flex-wrap items-center gap-1">{meta}</span> : null}
      </span>
    </>
  );

  return (
    <div className={rowClassName}>
      {onClick ? (
        <button
          type="button"
          onClick={onClick}
          disabled={disabled}
          className={cn(contentClassName, 'active:bg-secondary')}
        >
          {content}
        </button>
      ) : (
        <div className={contentClassName}>{content}</div>
      )}
      {trailing ? <span className="flex shrink-0 items-center pr-2">{trailing}</span> : null}
    </div>
  );
};
