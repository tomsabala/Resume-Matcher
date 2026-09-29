'use client';

import { useCallback } from 'react';
import type { Locale } from '@/i18n/config';
import { getMessages as getMessagesForLocale, type Messages } from './messages';
import { applyParams, getNestedValue } from './utils';

const messages = getMessagesForLocale('en');

/**
 * Hook to get the UI copy. The app is English-only, so the bundle is a
 * module-level constant; the hook survives as the components' single
 * translation entry point.
 *
 * Usage:
 * const { t } = useTranslations();
 * <button>{t('common.save')}</button>
 */
export function useTranslations() {
  /**
   * Translate a key. Supports dot notation for nested keys: t('common.save')
   */
  const t = useCallback((key: string, params?: Record<string, string | number>): string => {
    const translation = getNestedValue(messages as unknown as Record<string, unknown>, key);
    return applyParams(translation, params);
  }, []);

  return { t, messages, locale: 'en' as const };
}

/**
 * Get messages for a specific locale (for server components)
 */
export const getMessages = getMessagesForLocale;

/**
 * Translate a key for a specific locale (for server components)
 */
export function translate(
  locale: Locale,
  key: string,
  params?: Record<string, string | number>
): string {
  const messages = getMessagesForLocale(locale);
  const translation = getNestedValue(messages as unknown as Record<string, unknown>, key);
  return applyParams(translation, params);
}

export type { Messages };
