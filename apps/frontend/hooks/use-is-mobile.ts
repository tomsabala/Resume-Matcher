'use client';

import { useSyncExternalStore } from 'react';

/** Below Tailwind's `lg` (1024px) — the breakpoint every mobile branch in this app uses. */
export const MOBILE_MEDIA_QUERY = '(max-width: 1023.98px)';

function subscribe(onChange: () => void): () => void {
  const list = window.matchMedia(MOBILE_MEDIA_QUERY);
  list.addEventListener('change', onChange);
  return () => list.removeEventListener('change', onChange);
}

function getSnapshot(): boolean {
  return window.matchMedia(MOBILE_MEDIA_QUERY).matches;
}

function getServerSnapshot(): boolean {
  return false;
}

/**
 * `false` during SSR and hydration, then the real value. Callers MUST also gate the
 * two trees with `lg:hidden` / `hidden lg:block`, so the one-frame `false` window can
 * never paint the desktop tree on a phone — it paints nothing.
 */
export function useIsMobile(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
