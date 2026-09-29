/**
 * Internationalization configuration
 *
 * The app is English-only; `messages/en.json` is the sole bundle.
 */

export const locales = ['en'] as const;
export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = 'en';
