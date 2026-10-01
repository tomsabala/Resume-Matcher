/**
 * Text direction for *content*, not for the app chrome.
 *
 * The UI stays English and left-to-right; only the resume render surface flips
 * wholesale, and every other place that paints user content inside that chrome
 * uses per-node `dir="auto"` isolation instead. Plain module (no `'use client'`)
 * so the server-rendered print routes can import it too.
 *
 * The detector mirrors `app/services/language.py`: same block table, same two
 * constants, so the template picker and the server agree on what "contains
 * Hebrew" means. A workspace's content language is only the fallback — a
 * Hebrew resume in an English workspace still renders right-to-left.
 */

/** Content languages written right-to-left. */
const RTL_CONTENT_LANGUAGES: Record<string, true> = { he: true };

/**
 * Unicode block per supported non-Latin content language. A third language is
 * one row here, one in the backend's `SCRIPT_RANGES` and — if RTL — one in
 * `RTL_CONTENT_LANGUAGES`.
 */
const SCRIPT_RANGES: Record<string, [number, number]> = { he: [0x0590, 0x05ff] };

/** Fewer letters than this and the sample is noise: a heading, a date, "N/A". */
const MIN_SAMPLE_LETTERS = 20;

/**
 * Share of a sample's letters that must belong to one non-Latin script before
 * it decides the language. Hebrew prose stays far above this even when dense
 * with Latin tech terms, URLs and company names; English scores zero.
 */
const NON_LATIN_SHARE_THRESHOLD = 0.2;

const LETTER = /\p{L}/u;
const LATIN = /[A-Za-z]/;

/**
 * Every string *value* inside a string / array / object, recursively. Object
 * **keys** are skipped on purpose: they are English schema identifiers
 * (`workExperience`, `schemaVersion`) that would otherwise swamp the letter
 * count of a Hebrew document.
 */
function* strings(value: unknown): Generator<string> {
  if (typeof value === 'string') {
    yield value;
  } else if (Array.isArray(value)) {
    for (const item of value) yield* strings(item);
  } else if (value !== null && typeof value === 'object') {
    for (const item of Object.values(value)) yield* strings(item);
  }
}

/** `SCRIPT_RANGES` code for a letter, `'en'` for Latin, else nothing. */
function scriptOf(ch: string): string | null {
  const code = ch.codePointAt(0) ?? 0;
  for (const [language, [low, high]] of Object.entries(SCRIPT_RANGES)) {
    if (code >= low && code <= high) return language;
  }
  return LATIN.test(ch) ? 'en' : null;
}

/**
 * True when any string inside `value` carries one letter of `language`.
 *
 * The *any*-predicate, for the places where a single glyph is fatal (the
 * Latin-only LaTeX preamble) rather than the places that want the dominant
 * language.
 */
export function containsScript(value: unknown, language: string): boolean {
  const span = SCRIPT_RANGES[language];
  if (!span) return false;
  const [low, high] = span;
  for (const text of strings(value)) {
    for (const ch of text) {
      const code = ch.codePointAt(0) ?? 0;
      if (code >= low && code <= high) return true;
    }
  }
  return false;
}

/**
 * The language of `value`, or `null` when it carries too few letters to judge —
 * the caller then falls back to the workspace's content language.
 */
export function detectContentLanguage(value: unknown): string | null {
  const counts: Record<string, number> = {};
  let total = 0;
  for (const text of strings(value)) {
    for (const ch of text) {
      if (!LETTER.test(ch)) continue;
      const script = scriptOf(ch);
      if (!script) continue;
      counts[script] = (counts[script] ?? 0) + 1;
      total += 1;
    }
  }
  if (total < MIN_SAMPLE_LETTERS) return null;
  for (const language of Object.keys(SCRIPT_RANGES)) {
    if ((counts[language] ?? 0) / total >= NON_LATIN_SHARE_THRESHOLD) return language;
  }
  return 'en';
}

/** Text direction for a workspace content-language code. */
function directionFor(language: string | null | undefined): 'ltr' | 'rtl' {
  return language && RTL_CONTENT_LANGUAGES[language] ? 'rtl' : 'ltr';
}

/**
 * Text direction for a document, falling back to the workspace's content
 * language only while the document is too short to judge.
 */
export function directionForContent(
  content: unknown,
  fallbackLanguage?: string | null
): 'ltr' | 'rtl' {
  return directionFor(detectContentLanguage(content) ?? fallbackLanguage);
}
