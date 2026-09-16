import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LatexPanel } from '@/components/latex/latex-panel';
import { getTexCapabilities, getTexSource } from '@/lib/api/tex';
import type * as TexApi from '@/lib/api/tex';
import { DEFAULT_TEMPLATE_SETTINGS } from '@/lib/types/template-settings';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (key: string) => key }) }));

// Partial mock: the real `texFormatParams` builds the reload key, so the test
// exercises the same identity the component debounces on.
vi.mock('@/lib/api/tex', async (importOriginal) => {
  const actual = await importOriginal<typeof TexApi>();
  return {
    ...actual,
    getTexCapabilities: vi.fn(),
    getTexSource: vi.fn(),
    saveTexSource: vi.fn(),
    clearTexSource: vi.fn(),
    downloadTexSource: vi.fn(),
    compileTexPdf: vi.fn(),
  };
});

const load = vi.mocked(getTexSource);
const capabilities = vi.mocked(getTexCapabilities);

const panel = (settings = DEFAULT_TEMPLATE_SETTINGS) => (
  <LatexPanel
    resumeId="r-1"
    template="tex-classic"
    htmlTemplateSelected={false}
    onTemplateChange={() => {}}
    settings={settings}
    revision={0}
  />
);

const widerMargin = {
  ...DEFAULT_TEMPLATE_SETTINGS,
  margins: { ...DEFAULT_TEMPLATE_SETTINGS.margins, left: 25 },
};

describe('the LaTeX source panel', () => {
  beforeEach(() => {
    load.mockReset();
    load.mockResolvedValue({
      resume_id: 'r-1',
      source: '\\documentclass[a4paper,10pt]{article}',
      is_override: false,
      template: 'tex-classic',
      engine: 'pdflatex',
    });
    capabilities.mockReset();
    capabilities.mockResolvedValue({
      engine: 'pdflatex',
      can_compile: true,
      templates: ['tex-classic', 'tex-compact'],
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('regenerates the source once the formatting controls settle', async () => {
    const view = render(panel());
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));

    vi.useFakeTimers();
    view.rerender(panel(widerMargin));

    // A margin slider emits a value per pixel of drag.
    expect(load).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(load).toHaveBeenCalledTimes(2);
    expect(load).toHaveBeenLastCalledWith('r-1', {
      template: 'tex-classic',
      format: widerMargin,
    });
  });

  it('never refetches over unsaved LaTeX', async () => {
    const view = render(panel());
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    const editor = screen.getByLabelText('latex.sourceLabel') as HTMLTextAreaElement;

    await act(async () => {
      // The user's hand-edit, not yet saved.
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
      setter.call(editor, '% mine\n\\documentclass[a4paper,10pt]{article}');
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(editor.value).toContain('% mine');

    vi.useFakeTimers();
    view.rerender(panel(widerMargin));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    expect(load).toHaveBeenCalledTimes(1);
    expect(editor.value).toContain('% mine');
  });
});
