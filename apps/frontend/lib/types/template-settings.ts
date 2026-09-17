/**
 * Resume Template Settings
 *
 * Defines the structure for template selection and formatting controls.
 * These settings affect both the live preview and PDF generation.
 */

export type TemplateType =
  | 'swiss-single'
  | 'swiss-two-column'
  | 'modern'
  | 'modern-two-column'
  | 'latex'
  | 'clean'
  | 'vivid'
  | 'tex-classic'
  | 'tex-compact';

export type PageSize = 'A4' | 'LETTER';

export type AccentColor = 'blue' | 'green' | 'orange' | 'red';

/**
 * Spacing levels for the four spacing axes (section, item, bullet lead-in,
 * line height). Level 1 is the tightest the layout stays legible at, 9 the
 * airiest; the neutral reference look sits mid-range (see
 * `DEFAULT_TEMPLATE_SETTINGS`).
 */
export type SpacingLevel = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;

/**
 * Font levels for the two type axes (base size, header scale). These stay 1-5:
 * the LaTeX `extarticle` class offers 8/9/10/11/12pt and nothing below 8pt, so
 * there is no honest step to add in either direction.
 */
export type FontLevel = 1 | 2 | 3 | 4 | 5;

/** The level buttons each axis offers, so no UI hardcodes the range. */
export const SPACING_LEVELS: readonly SpacingLevel[] = [1, 2, 3, 4, 5, 6, 7, 8, 9];
export const FONT_LEVELS: readonly FontLevel[] = [1, 2, 3, 4, 5];

export type HeaderFontFamily = 'serif' | 'sans-serif' | 'mono';
export type BodyFontFamily = 'serif' | 'sans-serif' | 'mono';

export interface MarginSettings {
  top: number; // 5-25mm
  bottom: number;
  left: number;
  right: number;
}

export interface SpacingSettings {
  section: SpacingLevel; // Gap between major sections
  item: SpacingLevel; // Gap between items within sections
  lineHeight: SpacingLevel; // Text line height
  bulletLeadIn: SpacingLevel; // Gap above a bullet list (LaTeX templates only)
}

export interface FontSizeSettings {
  base: FontLevel; // Overall text scale
  headerScale: FontLevel; // Header size multiplier
  headerFont: HeaderFontFamily; // Header font family
  bodyFont: BodyFontFamily; // Body text font family
}

/**
 * Version marker for a persisted `TemplateSettings` payload.
 *
 * v2 widened the four spacing axes from levels 1-5 to 1-9 by renumbering: an
 * old level `n` is the new level `n + 2`, so every physical value is preserved.
 * A v1 payload's levels are all valid v2 levels too, which makes the two
 * indistinguishable without this marker — hence the marker.
 */
export const TEMPLATE_SETTINGS_VERSION = 2 as const;

export interface TemplateSettings {
  settingsVersion: typeof TEMPLATE_SETTINGS_VERSION;
  template: TemplateType;
  pageSize: PageSize;
  margins: MarginSettings;
  spacing: SpacingSettings;
  fontSize: FontSizeSettings;
  compactMode: boolean; // Apply tighter spacing across the board
  showContactIcons: boolean; // Show icons next to contact info
  accentColor: AccentColor; // Accent color for Modern template
}

/**
 * Default template settings
 */
export const DEFAULT_TEMPLATE_SETTINGS: TemplateSettings = {
  settingsVersion: TEMPLATE_SETTINGS_VERSION,
  template: 'swiss-single',
  pageSize: 'A4',
  margins: { top: 10, bottom: 10, left: 10, right: 10 },
  spacing: { section: 5, item: 4, lineHeight: 5, bulletLeadIn: 4 },
  fontSize: { base: 3, headerScale: 3, headerFont: 'serif', bodyFont: 'sans-serif' },
  compactMode: false,
  showContactIcons: false,
  accentColor: 'blue',
};

/**
 * Page size dimensions for display
 */
export const PAGE_SIZE_INFO: Record<PageSize, { name: string; dimensions: string }> = {
  A4: { name: 'A4', dimensions: '210 × 297 mm' },
  LETTER: { name: 'US Letter', dimensions: '8.5 × 11 in' },
};

/**
 * CSS Variable mappings for spacing levels
 */
export const SECTION_SPACING_MAP: Record<SpacingLevel, string> = {
  1: '0.125rem', // 2px
  2: '0.25rem', // 4px
  3: '0.375rem', // 6px
  4: '0.625rem', // 10px
  5: '1rem', // 16px - default
  6: '1.25rem', // 20px
  7: '1.5rem', // 24px
  8: '2rem', // 32px
  9: '2.5rem', // 40px
};

export const ITEM_SPACING_MAP: Record<SpacingLevel, string> = {
  1: '0rem', // 0px
  2: '0.0625rem', // 1px
  3: '0.125rem', // 2px
  4: '0.25rem', // 4px - default
  5: '0.5rem', // 8px
  6: '0.75rem', // 12px
  7: '1rem', // 16px
  8: '1.5rem', // 24px
  9: '2rem', // 32px
};

export const LINE_HEIGHT_MAP: Record<SpacingLevel, number> = {
  1: 1.05, // tightest
  2: 1.1,
  3: 1.15,
  4: 1.25,
  5: 1.35, // default
  6: 1.45,
  7: 1.55,
  8: 1.7,
  9: 1.85, // loosest
};

export const FONT_SIZE_MAP: Record<FontLevel, string> = {
  1: '11px',
  2: '12px',
  3: '14px', // default
  4: '15px',
  5: '16px',
};

export const HEADER_SCALE_MAP: Record<FontLevel, number> = {
  1: 1.5,
  2: 1.75,
  3: 2, // default
  4: 2.25,
  5: 2.5,
};

// Section header scale (SUMMARY, EXPERIENCE, etc.) - slightly smaller than name
export const SECTION_HEADER_SCALE_MAP: Record<FontLevel, number> = {
  1: 1.0, // 1.0x
  2: 1.1, // 1.1x
  3: 1.2, // 1.2x - default
  4: 1.3, // 1.3x
  5: 1.4, // 1.4x
};

/**
 * CJK fallback ordering, per content locale.
 *
 * Noto Sans SC, KR and JP all cover Han ideographs, and SC additionally covers
 * ~93% of kana — so whichever face is listed first wins for any shared
 * codepoint. A single static order cannot be right for every locale:
 *
 *   - SC first  → correct Chinese, but Japanese kana renders in SC forms
 *   - JP first  → correct Japanese, but Chinese Han renders in JP forms
 *   - Hangul    → only KR covers it meaningfully (SC covers 0.7%, i.e. tofu)
 *
 * so the stack is ordered by the locale the document is actually rendered in.
 */
const CJK_FONT_STACKS: Record<string, string[]> = {
  zh: ['--font-noto-sans-sc', '--font-noto-sans-jp', '--font-noto-sans-kr'],
  ja: ['--font-noto-sans-jp', '--font-noto-sans-kr', '--font-noto-sans-sc'],
  ko: ['--font-noto-sans-kr', '--font-noto-sans-jp', '--font-noto-sans-sc'],
};

const DEFAULT_CJK_STACK = CJK_FONT_STACKS.zh;

const cjkVars = (locale?: string): string => {
  const key = (locale ?? '').toLowerCase().split('-')[0];
  const stack = CJK_FONT_STACKS[key] ?? DEFAULT_CJK_STACK;
  return stack.map((v) => `var(${v})`).join(', ');
};

// Header font family mapping. Exported as functions of the locale; the eager
// maps below preserve the previous default-ordering API for existing callers.
export const buildHeaderFontMap = (locale?: string): Record<HeaderFontFamily, string> => ({
  serif: `ui-serif, Georgia, Cambria, "Times New Roman", ${cjkVars(locale)}, Times, serif`,
  'sans-serif': `ui-sans-serif, system-ui, ${cjkVars(locale)}, sans-serif, "Apple Color Emoji", "Segoe UI Emoji"`,
  mono: `ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, ${cjkVars(locale)}, monospace`,
});

export const buildBodyFontMap = (locale?: string): Record<BodyFontFamily, string> =>
  buildHeaderFontMap(locale);

export const HEADER_FONT_MAP: Record<HeaderFontFamily, string> = buildHeaderFontMap();
export const BODY_FONT_MAP: Record<BodyFontFamily, string> = buildBodyFontMap();

/**
 * Accent color mapping for Modern template
 */
export const ACCENT_COLOR_MAP: Record<
  AccentColor,
  { primary: string; light: string; name: string }
> = {
  blue: { primary: '#1D4ED8', light: '#DBEAFE', name: 'Blue' },
  green: { primary: '#15803D', light: '#DCFCE7', name: 'Green' },
  orange: { primary: '#EA580C', light: '#FED7AA', name: 'Orange' },
  red: { primary: '#DC2626', light: '#FEE2E2', name: 'Red' },
};

// Compact mode multiplier (applied to spacing values only, NOT line-height)
export const COMPACT_MULTIPLIER = 0.6;

// Line height gets a gentler reduction in compact mode
export const COMPACT_LINE_HEIGHT_MULTIPLIER = 0.92;

/**
 * Convert TemplateSettings to CSS custom properties
 */
export function settingsToCssVars(
  settings?: TemplateSettings,
  locale?: string
): React.CSSProperties {
  const s = settings || DEFAULT_TEMPLATE_SETTINGS;
  const compact = s.compactMode ? COMPACT_MULTIPLIER : 1;

  // Margins remain literal; compact mode only affects spacing/line-height.
  const marginTop = s.margins.top;
  const marginBottom = s.margins.bottom;
  const marginLeft = s.margins.left;
  const marginRight = s.margins.right;

  // Get accent colors for Modern template
  const accentColors = ACCENT_COLOR_MAP[s.accentColor];

  return {
    '--section-gap': s.compactMode
      ? `calc(${SECTION_SPACING_MAP[s.spacing.section]} * ${compact})`
      : SECTION_SPACING_MAP[s.spacing.section],
    '--item-gap': s.compactMode
      ? `calc(${ITEM_SPACING_MAP[s.spacing.item]} * ${compact})`
      : ITEM_SPACING_MAP[s.spacing.item],
    // Line-height uses a gentler multiplier to avoid text overlap
    '--line-height': s.compactMode
      ? LINE_HEIGHT_MAP[s.spacing.lineHeight] * COMPACT_LINE_HEIGHT_MULTIPLIER
      : LINE_HEIGHT_MAP[s.spacing.lineHeight],
    '--font-size-base': FONT_SIZE_MAP[s.fontSize.base],
    '--header-scale': HEADER_SCALE_MAP[s.fontSize.headerScale],
    '--section-header-scale': SECTION_HEADER_SCALE_MAP[s.fontSize.headerScale],
    '--header-font': buildHeaderFontMap(locale)[s.fontSize.headerFont],
    '--body-font': buildBodyFontMap(locale)[s.fontSize.bodyFont],
    '--margin-top': `${marginTop}mm`,
    '--margin-bottom': `${marginBottom}mm`,
    '--margin-left': `${marginLeft}mm`,
    '--margin-right': `${marginRight}mm`,
    // Accent colors for Modern template
    '--resume-accent-primary': accentColors.primary,
    '--resume-accent-light': accentColors.light,
  } as React.CSSProperties;
}

/**
 * Template metadata for UI display
 */
export interface TemplateInfo {
  id: TemplateType;
  name: string;
  description: string;
  /**
   * Which renderer produces the PDF: headless Chromium over the print route,
   * or the LaTeX engine. One picker, two targets — the selection decides the
   * export, so nothing silently renders with the other engine.
   */
  target: 'html' | 'tex';
}

export const TEMPLATE_OPTIONS: TemplateInfo[] = [
  {
    id: 'swiss-single',
    name: 'Single Column',
    description: 'Traditional full-width layout with maximum content density',
    target: 'html',
  },
  {
    id: 'swiss-two-column',
    name: 'Two Column',
    description: 'Experience-focused main column with sidebar for skills',
    target: 'html',
  },
  {
    id: 'modern',
    name: 'Modern',
    description: 'Colorful accents with customizable theme colors',
    target: 'html',
  },
  {
    id: 'modern-two-column',
    name: 'Modern Two Column',
    description: 'Two-column layout with modern colorful accents and themes',
    target: 'html',
  },
  {
    id: 'latex',
    name: 'Academic Serif',
    description: 'Browser-rendered serif layout with ruled section headers',
    target: 'html',
  },
  {
    id: 'clean',
    name: 'Clean',
    description: 'Minimal sans layout with large understated section headers',
    target: 'html',
  },
  {
    id: 'vivid',
    name: 'Vivid',
    description: 'Colorful two-column layout with accent headers and arrow bullets',
    target: 'html',
  },
  {
    id: 'tex-classic',
    name: 'LaTeX Classic',
    description: 'Engine-compiled Computer Modern with ruled small-caps headings',
    target: 'tex',
  },
  {
    id: 'tex-compact',
    name: 'LaTeX Compact',
    description: 'Engine-compiled, denser: tighter margins and unruled headings',
    target: 'tex',
  },
];

/**
 * Whether a template is compiled by the LaTeX engine rather than Chromium.
 * Read from `TEMPLATE_OPTIONS` so adding a template is a one-line change and
 * no call site pattern-matches on the id.
 */
export function isTexTemplate(template: TemplateType): boolean {
  return TEMPLATE_OPTIONS.find((option) => option.id === template)?.target === 'tex';
}

/**
 * Signature font presets for single-typeface templates.
 *
 * LaTeX and Clean bind their headers to `--header-font` and body to `--body-font`, so
 * both font controls are live. Selecting one of these templates applies its signature
 * fonts (so it matches its reference look by default); the user can then override either
 * control. Templates not listed here keep the current font settings on selection.
 */
export const TEMPLATE_FONT_PRESETS: Partial<
  Record<TemplateType, { headerFont: HeaderFontFamily; bodyFont: BodyFontFamily }>
> = {
  latex: { headerFont: 'serif', bodyFont: 'serif' },
  clean: { headerFont: 'sans-serif', bodyFont: 'sans-serif' },
};

/**
 * Return settings with the given template applied, seeding the template's signature
 * fonts when it has a preset. Use this at every template-change entry point so the
 * single-typeface templates render their reference look by default.
 */
export function applyTemplatePreset(
  settings: TemplateSettings,
  template: TemplateType
): TemplateSettings {
  const preset = TEMPLATE_FONT_PRESETS[template];
  if (!preset) return { ...settings, template };
  return {
    ...settings,
    template,
    fontSize: { ...settings.fontSize, headerFont: preset.headerFont, bodyFont: preset.bodyFont },
  };
}
