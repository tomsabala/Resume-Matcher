/**
 * Text direction for *content*, not for the app chrome.
 *
 * The UI stays English and left-to-right; only the resume render surface flips
 * wholesale, and every other place that paints user content inside that chrome
 * uses per-node `dir="auto"` isolation instead. Plain module (no `'use client'`)
 * so the server-rendered print routes can import it too.
 */

/** Content languages written right-to-left. */
const RTL_CONTENT_LANGUAGES: Record<string, true> = { he: true };

/** Text direction for a workspace content-language code. */
export function directionFor(language: string | null | undefined): 'ltr' | 'rtl' {
  return language && RTL_CONTENT_LANGUAGES[language] ? 'rtl' : 'ltr';
}
