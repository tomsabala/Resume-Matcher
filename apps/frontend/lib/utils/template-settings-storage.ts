import {
  DEFAULT_TEMPLATE_SETTINGS,
  TEMPLATE_OPTIONS,
  TEMPLATE_SETTINGS_VERSION,
  type FontSizeSettings,
  type MarginSettings,
  type SpacingLevel,
  type SpacingSettings,
  type TemplateSettings,
} from '@/lib/types/template-settings';
import { safeStorage } from '@/lib/utils/resume-draft-storage';

/**
 * The last template and formatting choice made in this browser.
 *
 * It is a *default*, not the choice itself: a resume's own
 * ``template_settings`` wins, and this is what a resume that has none yet
 * starts from — so opening an older resume keeps showing what the user last
 * designed instead of resetting to ``swiss-single``.
 */
export const TEMPLATE_SETTINGS_STORAGE_KEY = 'resume_builder_settings';

/** What a previous session may have left in storage: any subset, any version. */
type StoredTemplateSettings = Partial<
  Omit<TemplateSettings, 'margins' | 'spacing' | 'fontSize'>
> & {
  margins?: Partial<MarginSettings>;
  spacing?: Partial<SpacingSettings>;
  fontSize?: Partial<FontSizeSettings>;
};

/**
 * Bring a stored payload up to the current settings version.
 *
 * v2 widened the four spacing axes from levels 1-5 to 1-9 by renumbering: old
 * level `n` is new level `n + 2`, which preserves every physical value so no
 * existing resume reflows. The version marker is what makes this decidable —
 * every v1 level is also a valid v2 level, so the two payloads are
 * indistinguishable by their numbers alone and only the absence of
 * `settingsVersion` identifies a v1 one. Font levels are untouched (they stay
 * 1-5), as is everything outside `spacing`.
 */
function upgradeStoredSettings(parsed: StoredTemplateSettings): StoredTemplateSettings {
  if ('settingsVersion' in parsed) return parsed;
  const stored: Partial<SpacingSettings> = parsed.spacing ?? {};
  const shifted = (axis: keyof SpacingSettings): SpacingLevel => {
    const level = stored[axis];
    // `bulletLeadIn` may be absent from a v1 payload, and a level outside the
    // old 1-5 range is not a v1 level at all: both fall back to the neutral.
    return typeof level === 'number' && Number.isInteger(level) && level >= 1 && level <= 5
      ? ((level + 2) as SpacingLevel)
      : DEFAULT_TEMPLATE_SETTINGS.spacing[axis];
  };
  return {
    ...parsed,
    spacing: {
      section: shifted('section'),
      item: shifted('item'),
      lineHeight: shifted('lineHeight'),
      bulletLeadIn: shifted('bulletLeadIn'),
    },
  };
}

/** The stored settings, merged over the defaults; defaults when unreadable. */
export function readTemplateSettings(): TemplateSettings {
  if (typeof window === 'undefined') return DEFAULT_TEMPLATE_SETTINGS;
  try {
    const saved = safeStorage.get(TEMPLATE_SETTINGS_STORAGE_KEY);
    if (!saved) return DEFAULT_TEMPLATE_SETTINGS;
    const raw: unknown = JSON.parse(saved);
    if (typeof raw !== 'object' || raw === null) return DEFAULT_TEMPLATE_SETTINGS;
    // Cast, not validation: the merge below fills whatever the payload omits
    // from the defaults, and the one stored value that would misroute an export
    // — the template id — is checked against TEMPLATE_OPTIONS afterwards.
    const parsed = upgradeStoredSettings(raw as StoredTemplateSettings);
    const merged: TemplateSettings = {
      ...DEFAULT_TEMPLATE_SETTINGS,
      ...parsed,
      margins: { ...DEFAULT_TEMPLATE_SETTINGS.margins, ...parsed.margins },
      spacing: { ...DEFAULT_TEMPLATE_SETTINGS.spacing, ...parsed.spacing },
      fontSize: { ...DEFAULT_TEMPLATE_SETTINGS.fontSize, ...parsed.fontSize },
      settingsVersion: TEMPLATE_SETTINGS_VERSION,
    };
    // A stored id that no longer exists would route the export to a renderer
    // that cannot produce it, so it never survives a read.
    const known = TEMPLATE_OPTIONS.some((option) => option.id === merged.template);
    return known ? merged : { ...merged, template: DEFAULT_TEMPLATE_SETTINGS.template };
  } catch {
    return DEFAULT_TEMPLATE_SETTINGS;
  }
}

export function writeTemplateSettings(settings: TemplateSettings): void {
  safeStorage.set(
    TEMPLATE_SETTINGS_STORAGE_KEY,
    JSON.stringify({ ...settings, settingsVersion: TEMPLATE_SETTINGS_VERSION })
  );
}
