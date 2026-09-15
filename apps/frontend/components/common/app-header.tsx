'use client';

import { usePathname } from 'next/navigation';
import { WorkspaceSwitcher } from '@/components/common/workspace-switcher';

/**
 * Thin application header carrying the workspace switcher.
 *
 * Hidden on the landing page and on print routes, which are full-bleed
 * surfaces with no chrome.
 */
export function AppHeader() {
  const pathname = usePathname();
  if (pathname === '/' || pathname.startsWith('/print')) return null;

  return (
    <header className="flex items-center justify-end border-b-2 border-black bg-background px-4 py-2">
      <WorkspaceSwitcher />
    </header>
  );
}
