'use client';

import { useEffect, useState } from 'react';

/**
 * `value`, held back until it has stopped changing for `delayMs`.
 *
 * For keys that drive expensive work: a margin slider emits a value per pixel
 * of drag, and a LaTeX compile is seconds of engine time. State starts at
 * `value`, so the first render acts immediately and only later changes wait.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    if (value === debounced) return;
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, debounced, delayMs]);

  return debounced;
}
