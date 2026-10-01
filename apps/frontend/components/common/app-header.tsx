'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { ChevronLeft, KanbanSquare, Layers, Settings } from 'lucide-react';

import { WorkspaceSwitcher } from '@/components/common/workspace-switcher';
import { isDetailRoute } from '@/components/common/bottom-nav';
import { useTranslations } from '@/lib/i18n';
import { cn } from '@/lib/utils';

/** Route title key, resolved against keys that already exist in every locale. */
function routeTitleKey(pathname: string): string | null {
  if (pathname.startsWith('/dashboard')) return 'nav.dashboard';
  if (pathname.startsWith('/tracker')) return 'nav.applicationTracker';
  if (pathname.startsWith('/interview-prep')) return 'nav.interviewPrep';
  if (pathname.startsWith('/settings')) return 'nav.settings';
  if (pathname.startsWith('/builder')) return 'nav.builder';
  if (pathname.startsWith('/tailor')) return 'nav.tailor';
  if (pathname.startsWith('/resume-wizard')) return 'nav.builder';
  if (pathname.startsWith('/resumes')) return 'nav.dashboard';
  if (pathname.startsWith('/compare')) return 'dashboard.selection.compare';
  return null;
}

/**
 * Routes whose only other link is the `lg:hidden` tab bar, so above `lg` this
 * header is the sole way in. Keep it the exact complement of `bottom-nav`.
 */
const DESKTOP_LINKS = [
  { href: '/interview-prep', icon: Layers, labelKey: 'nav.interviewPrep' },
  { href: '/tracker', icon: KanbanSquare, labelKey: 'nav.applicationTracker' },
  { href: '/settings', icon: Settings, labelKey: 'nav.settings' },
] as const;

/**
 * Route-aware top bar: back chevron on detail routes, the route title, the
 * desktop links to Interview Prep, Tracker and Settings (the tab bar owns them
 * below `lg`), and the workspace switcher.
 *
 * Hidden on print routes, which are full-bleed surfaces with no chrome.
 */
export function AppHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslations();

  if (pathname.startsWith('/print')) return null;

  const titleKey = routeTitleKey(pathname);

  return (
    <header className="sticky top-0 z-40 flex min-h-14 items-center gap-2 border-b-2 border-black bg-background px-2 lg:px-4 no-print">
      {isDetailRoute(pathname) && (
        <button
          type="button"
          onClick={() => router.back()}
          aria-label={t('common.back')}
          className="flex h-11 w-11 shrink-0 items-center justify-center lg:hidden"
        >
          <ChevronLeft className="h-5 w-5" />
        </button>
      )}
      <span className="min-w-0 flex-1 truncate font-mono text-xs font-bold uppercase tracking-wider lg:hidden">
        {titleKey ? t(titleKey) : ''}
      </span>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        {DESKTOP_LINKS.map(({ href, icon: Icon, labelKey }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              aria-label={t(labelKey)}
              title={t(labelKey)}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'hidden h-11 w-11 items-center justify-center border border-black lg:flex',
                active ? 'bg-black text-white' : 'bg-white text-black hover:bg-paper-tint'
              )}
            >
              <Icon className="h-5 w-5" />
            </Link>
          );
        })}
        <WorkspaceSwitcher />
      </div>
    </header>
  );
}
