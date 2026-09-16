import {
  DEFAULT_TEMPLATE_SETTINGS,
  TEMPLATE_OPTIONS,
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

/** The stored settings, merged over the defaults; defaults when unreadable. */
export function readTemplateSettings(): TemplateSettings {
  if (typeof window === 'undefined') return DEFAULT_TEMPLATE_SETTINGS;
  try {
    const saved = safeStorage.get(TEMPLATE_SETTINGS_STORAGE_KEY);
    if (!saved) return DEFAULT_TEMPLATE_SETTINGS;
    const parsed = JSON.parse(saved);
    const merged: TemplateSettings = {
      ...DEFAULT_TEMPLATE_SETTINGS,
      ...parsed,
      margins: { ...DEFAULT_TEMPLATE_SETTINGS.margins, ...parsed.margins },
      spacing: { ...DEFAULT_TEMPLATE_SETTINGS.spacing, ...parsed.spacing },
      fontSize: { ...DEFAULT_TEMPLATE_SETTINGS.fontSize, ...parsed.fontSize },
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
  safeStorage.set(TEMPLATE_SETTINGS_STORAGE_KEY, JSON.stringify(settings));
}
