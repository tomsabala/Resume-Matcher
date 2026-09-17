import { afterEach, describe, expect, it } from 'vitest';
import { settingsToCssVars } from '@/lib/types/template-settings';
import {
  TEMPLATE_SETTINGS_STORAGE_KEY,
  readTemplateSettings,
} from '@/lib/utils/template-settings-storage';

/**
 * v2 widened the spacing axes from 1-5 to 1-9 by renumbering, so the numbers in
 * a payload written before the change mean tighter spacing than the same
 * numbers mean now. Reading one without shifting it would silently reflow every
 * resume the user had already designed.
 */
const V1_PAYLOAD = {
  template: 'tex-classic',
  spacing: { section: 3, item: 2, lineHeight: 3, bulletLeadIn: 2 },
  fontSize: { base: 3, headerScale: 3, headerFont: 'serif', bodyFont: 'sans-serif' },
  margins: { top: 10, bottom: 10, left: 10, right: 10 },
  pageSize: 'A4',
  compactMode: false,
  showContactIcons: false,
  accentColor: 'blue',
};

afterEach(() => {
  localStorage.clear();
});

describe('reading settings stored before the spacing levels widened', () => {
  it('keeps the physical spacing by shifting the levels', () => {
    localStorage.setItem(TEMPLATE_SETTINGS_STORAGE_KEY, JSON.stringify(V1_PAYLOAD));

    const upgraded = readTemplateSettings();

    expect(upgraded.settingsVersion).toBe(2);
    expect(upgraded.spacing).toEqual({ section: 5, item: 4, lineHeight: 5, bulletLeadIn: 4 });
    // What the user actually sees: the old levels' own 16px/4px/1.35 look.
    const vars = settingsToCssVars(upgraded) as Record<string, string | number>;
    expect(vars['--section-gap']).toBe('1rem');
    expect(vars['--item-gap']).toBe('0.25rem');
    expect(vars['--line-height']).toBe(1.35);
    // Font levels never moved, and nothing outside `spacing` is touched.
    expect(upgraded.fontSize.base).toBe(3);
    expect(upgraded.template).toBe('tex-classic');

    // The bullet lead-in shipped mid-v1, so a payload may predate it: that axis
    // lands on the neutral rather than on a shifted absent value.
    const { section, item, lineHeight } = V1_PAYLOAD.spacing;
    localStorage.setItem(
      TEMPLATE_SETTINGS_STORAGE_KEY,
      JSON.stringify({ ...V1_PAYLOAD, spacing: { section, item, lineHeight } })
    );

    expect(readTemplateSettings().spacing).toEqual({
      section: 5,
      item: 4,
      lineHeight: 5,
      bulletLeadIn: 4,
    });
  });
});
