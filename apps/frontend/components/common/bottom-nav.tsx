'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { KanbanSquare, LayoutGrid, Plus, Settings } from 'lucide-react';

import { useTranslations } from '@/lib/i18n';
import { cn } from '@/lib/utils';

/** Routes that show the tab bar; the active tab is the longest matching prefix. */
const TAB_ROOTS = ['/dashboard', '/tracker', '/settings'] as const;
/** Routes that replace the tab bar with a back chevron and their own action bar. */
const DETAIL_ROUTES = ['/builder', '/resumes', '/tailor', '/compare', '/resume-wizard'] as const;

export function isTabRoute(pathname: string): boolean {
  if (pathname === '/' || pathname.startsWith('/print')) return false;
  if (DETAIL_ROUTES.some((route) => pathname === route || pathname.startsWith(`${route}/`))) {
    return false;
  }
  return TAB_ROOTS.some((route) => pathname === route || pathname.startsWith(`${route}/`));
}

export function isDetailRoute(pathname: string): boolean {
  return DETAIL_ROUTES.some((route) => pathname === route || pathname.startsWith(`${route}/`));
}

/**
 * Fixed four-slot phone navigation. `sticky bottom-0` on an in-flow flex child pins to
 * the viewport bottom when the document is taller and sits at the flow end otherwise,
 * so no page needs bottom padding and no spacer is required. Never `fixed`.
 */
export function BottomNav() {
  const pathname = usePathname();
  const { t } = useTranslations();

  if (!isTabRoute(pathname)) return null;

  const slots = [
    { href: '/dashboard', icon: LayoutGrid, label: t('nav.tabs.resumes'), action: false },
    { href: '/tracker', icon: KanbanSquare, label: t('nav.tabs.tracker'), action: false },
    { href: '/tailor', icon: Plus, label: t('nav.tabs.create'), action: true },
    { href: '/settings', icon: Settings, label: t('nav.tabs.settings'), action: false },
  ] as const;

  return (
    <nav
      aria-label={t('nav.tabs.resumes')}
      className="sticky bottom-0 z-40 grid grid-cols-4 border-t-2 border-black bg-background lg:hidden no-print"
      style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
    >
      {slots.map(({ href, icon: Icon, label, action }) => {
        const active = !action && (pathname === href || pathname.startsWith(`${href}/`));
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'flex min-h-14 flex-col items-center justify-center gap-0.5 border-r border-black last:border-r-0 font-mono text-[10px] uppercase tracking-wide',
              action && 'bg-primary text-white',
              !action && (active ? 'bg-black text-white' : 'bg-background text-ink-soft')
            )}
          >
            <Icon className="h-5 w-5" aria-hidden="true" />
            <span>{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
