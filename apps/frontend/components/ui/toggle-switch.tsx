'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Swiss International Style Toggle Switch Component
 *
 * Design Principles:
 * - Square corners (rounded-none on container, pill shape for toggle)
 * - High contrast states
 * - Clear label and description
 */

export interface ToggleSwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
  className?: string;
}

export const ToggleSwitch: React.FC<ToggleSwitchProps> = ({
  checked,
  onCheckedChange,
  label,
  description,
  disabled = false,
  className,
}) => {
  const labelId = React.useId();

  const handleToggle = () => {
    if (!disabled) {
      onCheckedChange(!checked);
    }
  };

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      // The label alone is the accessible name; the state description below it
      // is supplementary and must not be appended to it.
      aria-labelledby={labelId}
      disabled={disabled}
      onClick={handleToggle}
      className={cn(
        // The whole row is the hit target — a 28px switch alone is under the
        // 44px touch floor.
        'flex w-full items-center justify-between p-4 border border-black bg-white text-left',
        'shadow-sw-sm',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-700 focus-visible:ring-offset-2',
        disabled && 'opacity-50 cursor-not-allowed',
        className
      )}
    >
      <span className="flex-1 mr-4">
        <span id={labelId} className="block font-mono text-sm font-bold uppercase tracking-wider">
          {label}
        </span>
        {description && (
          <span className="block font-sans text-xs text-steel-grey mt-1">{description}</span>
        )}
      </span>
      <span
        aria-hidden="true"
        className={cn(
          'relative inline-flex h-7 w-14 shrink-0 items-center',
          'border-2 border-black transition-colors',
          checked ? 'bg-blue-700' : 'bg-paper-tint'
        )}
      >
        <span
          className={cn(
            'pointer-events-none block h-5 w-5 bg-white border border-black',
            'transition-transform duration-200',
            checked ? 'translate-x-7' : 'translate-x-1'
          )}
        />
      </span>
    </button>
  );
};
