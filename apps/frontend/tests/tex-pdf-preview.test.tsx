import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TexPdfPreview } from '@/components/latex/tex-pdf-preview';
import { compileTexPdf, TexUnavailableError } from '@/lib/api/tex';
import type * as TexApi from '@/lib/api/tex';
import { DEFAULT_TEMPLATE_SETTINGS } from '@/lib/types/template-settings';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (key: string) => key }) }));

// Partial mock: only the compile is faked, so the real `texFormatParams`
// builds the reload key the debounce keys off.
vi.mock('@/lib/api/tex', async (importOriginal) => {
  const actual = await importOriginal<typeof TexApi>();
  return { ...actual, compileTexPdf: vi.fn() };
});

const compile = vi.mocked(compileTexPdf);

describe('the LaTeX tab preview', () => {
  beforeEach(() => {
    compile.mockReset();
    compile.mockResolvedValue(new Blob(['%PDF-1.7'], { type: 'application/pdf' }));
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:compiled'),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows the engine-compiled PDF rather than a browser approximation', async () => {
    render(
      <TexPdfPreview
        resumeId="r-1"
        template="tex-classic"
        settings={DEFAULT_TEMPLATE_SETTINGS}
        revision={0}
      />
    );

    await waitFor(() => expect(screen.getByLabelText('latex.previewLabel')).toBeInTheDocument());
    expect(compile).toHaveBeenCalledWith('r-1', 'tex-classic', DEFAULT_TEMPLATE_SETTINGS);
    expect(screen.getByLabelText('latex.previewLabel')).toHaveAttribute('data', 'blob:compiled');
  });

  it('recompiles when the template the source editor shows changes', async () => {
    const view = render(
      <TexPdfPreview
        resumeId="r-1"
        template="tex-classic"
        settings={DEFAULT_TEMPLATE_SETTINGS}
        revision={0}
      />
    );
    await waitFor(() => expect(compile).toHaveBeenCalledTimes(1));

    view.rerender(
      <TexPdfPreview
        resumeId="r-1"
        template="tex-compact"
        settings={DEFAULT_TEMPLATE_SETTINGS}
        revision={0}
      />
    );

    await waitFor(() =>
      expect(compile).toHaveBeenLastCalledWith('r-1', 'tex-compact', DEFAULT_TEMPLATE_SETTINGS)
    );
  });

  it('recompiles when the saved source changes', async () => {
    const view = render(
      <TexPdfPreview
        resumeId="r-1"
        template="tex-classic"
        settings={DEFAULT_TEMPLATE_SETTINGS}
        revision={0}
      />
    );
    await waitFor(() => expect(compile).toHaveBeenCalledTimes(1));

    view.rerender(
      <TexPdfPreview
        resumeId="r-1"
        template="tex-classic"
        settings={DEFAULT_TEMPLATE_SETTINGS}
        revision={1}
      />
    );

    await waitFor(() => expect(compile).toHaveBeenCalledTimes(2));
  });

  it('waits for a dragged margin to settle before recompiling once', async () => {
    const view = render(
      <TexPdfPreview
        resumeId="r-1"
        template="tex-classic"
        settings={DEFAULT_TEMPLATE_SETTINGS}
        revision={0}
      />
    );
    await waitFor(() => expect(compile).toHaveBeenCalledTimes(1));

    vi.useFakeTimers();
    const dragged = {
      ...DEFAULT_TEMPLATE_SETTINGS,
      margins: { ...DEFAULT_TEMPLATE_SETTINGS.margins, left: 11 },
    };
    view.rerender(
      <TexPdfPreview resumeId="r-1" template="tex-classic" settings={dragged} revision={0} />
    );

    // A compile is seconds of engine time; a slider emits a value per pixel.
    expect(compile).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(compile).toHaveBeenCalledTimes(2);
    expect(compile).toHaveBeenLastCalledWith('r-1', 'tex-classic', dragged);
  });

  it('explains a missing engine instead of rendering an empty frame', async () => {
    compile.mockRejectedValue(new TexUnavailableError('no engine'));

    render(
      <TexPdfPreview
        resumeId="r-1"
        template="tex-classic"
        settings={DEFAULT_TEMPLATE_SETTINGS}
        revision={0}
      />
    );

    await waitFor(() => expect(screen.getByText('latex.noEngine')).toBeInTheDocument());
    expect(screen.queryByLabelText('latex.previewLabel')).not.toBeInTheDocument();
  });
});
