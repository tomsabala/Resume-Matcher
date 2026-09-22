'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

export interface SegmentedOption {
  id: string;
  label: string;
  disabled?: boolean;
}

export interface SegmentedProps {
  options: SegmentedOption[];
  value: string;
  onChange: (id: string) => void;
  ariaLabel: string;
  className?: string;
}

/** Equal-width two/three-way switch. `RetroTabs` is a scrolling strip and is wrong for a binary choice. */
export const Segmented: React.FC<SegmentedProps> = ({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}) => (
  <div role="group" aria-label={ariaLabel} className={cn('flex w-full', className)}>
    {options.map((option) => (
      <button
        key={option.id}
        type="button"
        aria-pressed={value === option.id}
        disabled={option.disabled}
        onClick={() => onChange(option.id)}
        className={cn(
          '-ml-px min-h-11 flex-1 border border-black px-4 font-mono text-xs uppercase tracking-wider first:ml-0 disabled:opacity-40',
          value === option.id ? 'bg-black text-white' : 'bg-white text-ink'
        )}
      >
        {option.label}
      </button>
    ))}
  </div>
);
