import { describe, expect, it } from 'vitest';
import { texFormatParams } from '@/lib/api/tex';
import { getResumePdfUrl } from '@/lib/api/resume';
import { DEFAULT_TEMPLATE_SETTINGS } from '@/lib/types/template-settings';

/**
 * The names and levels here are the LaTeX routes' query parameters, which are
 * the Chromium route's as well apart from the LaTeX-only `bulletLeadIn`. A
 * rename on either side without the other silently drops a control: the export
 * keeps the reference look whatever the panel says.
 */
describe('texFormatParams', () => {
  it('sends every control the engine reads, under the backend spelling', () => {
    const params = texFormatParams(DEFAULT_TEMPLATE_SETTINGS);

    expect(Object.fromEntries(params)).toEqual({
      pageSize: 'A4',
      marginTop: '10',
      marginBottom: '10',
      marginLeft: '10',
      marginRight: '10',
      sectionSpacing: '5',
      itemSpacing: '4',
      bulletLeadIn: '4',
      lineHeight: '5',
      fontSize: '3',
      headerScale: '3',
      compactMode: 'false',
    });
  });

  it('carries the panel values rather than the defaults', () => {
    const params = texFormatParams({
      ...DEFAULT_TEMPLATE_SETTINGS,
      pageSize: 'LETTER',
      margins: { top: 25, bottom: 5, left: 20, right: 15 },
      spacing: { section: 9, item: 1, lineHeight: 8, bulletLeadIn: 7 },
      fontSize: { ...DEFAULT_TEMPLATE_SETTINGS.fontSize, base: 1, headerScale: 5 },
      compactMode: true,
    });

    expect(params.get('pageSize')).toBe('LETTER');
    expect(params.get('marginLeft')).toBe('20');
    expect(params.get('sectionSpacing')).toBe('9');
    expect(params.get('itemSpacing')).toBe('1');
    expect(params.get('bulletLeadIn')).toBe('7');
    expect(params.get('lineHeight')).toBe('8');
    expect(params.get('fontSize')).toBe('1');
    expect(params.get('headerScale')).toBe('5');
    expect(params.get('compactMode')).toBe('true');
  });

  it('omits the margins when there are no settings, keeping the reference geometry', () => {
    // A parameterless render must stay the reference CV's paper-proportional
    // margins; sending 10mm defaults would silently retighten it.
    expect(texFormatParams().toString()).toBe('pageSize=A4');
  });

  it('never sends the HTML-only controls', () => {
    const params = texFormatParams(DEFAULT_TEMPLATE_SETTINGS);

    for (const key of ['headerFont', 'bodyFont', 'accentColor', 'showContactIcons', 'template']) {
      expect(params.has(key)).toBe(false);
    }
  });

  it('sends the LaTeX-only bullet lead-in that the Chromium route never gets', () => {
    const settings = {
      ...DEFAULT_TEMPLATE_SETTINGS,
      template: 'swiss-single' as const,
      spacing: { ...DEFAULT_TEMPLATE_SETTINGS.spacing, bulletLeadIn: 9 as const },
    };

    // The gap above a bullet list is a preamble length, so only the engine can
    // honour it. Emitting it on `/pdf` too would promise the browser rendering
    // a control it silently drops.
    expect(texFormatParams(settings).get('bulletLeadIn')).toBe('9');
    const chromiumUrl = new URL(getResumePdfUrl('r-1', settings), 'http://pdf.test');
    expect(chromiumUrl.searchParams.has('bulletLeadIn')).toBe(false);
  });
});
