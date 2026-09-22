'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

export interface MobileActionBarProps {
  children: React.ReactNode;
  /** true on a route that also shows the bottom tab bar, so the bar floats above it. */
  aboveNav?: boolean;
  className?: string;
}

/**
 * The thumb-zone primary action. `sticky` (not `fixed`) means it occupies flow space,
 * so no page needs bottom-padding compensation.
 */
export const MobileActionBar: React.FC<MobileActionBarProps> = ({
  children,
  aboveNav = false,
  className,
}) => (
  <div
    className={cn(
      'sticky z-30 flex items-center gap-2 border-t-2 border-black bg-background px-4 py-3 lg:hidden',
      aboveNav ? 'bottom-[var(--mobile-nav-h)]' : 'bottom-0',
      className
    )}
    style={
      aboveNav ? undefined : { paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom, 0px))' }
    }
  >
    {children}
  </div>
);
