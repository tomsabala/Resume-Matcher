import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { FormattingControls } from '@/components/builder/formatting-controls';
import {
  DEFAULT_TEMPLATE_SETTINGS,
  type TemplateSettings,
  type TemplateType,
} from '@/lib/types/template-settings';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (key: string) => key }) }));

const LEAD_IN_LABEL = 'builder.formatting.spacingBulletLeadIn:';

/**
 * The bullet lead-in is a LaTeX preamble length: only the engine can honour it.
 * Offering it live under an HTML template would promise the Chromium export a
 * gap it never receives.
 */
function mountPanel(template: TemplateType) {
  const settings: TemplateSettings = { ...DEFAULT_TEMPLATE_SETTINGS, template };
  const onChange = vi.fn();
  render(<FormattingControls settings={settings} onChange={onChange} />);
  const row = screen.getByText(LEAD_IN_LABEL).parentElement as HTMLElement;
  return {
    onChange,
    level: (value: string) => within(row).getByRole('button', { name: value }),
  };
}

describe('the bullet lead-in control', () => {
  it('sets the level on a LaTeX template', () => {
    const { onChange, level } = mountPanel('tex-classic');

    expect(level('9')).toBeEnabled();
    fireEvent.click(level('9'));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toEqual({
      ...DEFAULT_TEMPLATE_SETTINGS,
      template: 'tex-classic',
      spacing: { ...DEFAULT_TEMPLATE_SETTINGS.spacing, bulletLeadIn: 9 },
    });
  });

  it('stays inert under an HTML template', () => {
    const { onChange, level } = mountPanel('swiss-single');

    expect(level('9')).toBeDisabled();
    fireEvent.click(level('9'));

    expect(onChange).not.toHaveBeenCalled();
  });
});
