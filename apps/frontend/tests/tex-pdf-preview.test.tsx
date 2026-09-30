import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TexPdfPreview } from '@/components/latex/tex-pdf-preview';
import { compileTexPdf, TexUnavailableError } from '@/lib/api/tex';
import type * as TexApi from '@/lib/api/tex';
import { DEFAULT_TEMPLATE_SETTINGS } from '@/lib/types/template-settings';

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({
    t: (key: string, params?: Record<string, string | number>) =>
      params ? `${key}:${Object.values(params).join(',')}` : key,
  }),
}));

// Partial mock: only the compile is faked, so the real `texFormatParams`
// builds the reload key the debounce keys off.
vi.mock('@/lib/api/tex', async (importOriginal) => {
  const actual = await importOriginal<typeof TexApi>();
  return { ...actual, compileTexPdf: vi.fn() };
});

// jsdom has no canvas raster and no worker, so pdf.js itself is stubbed. What
// the component owes its caller is what these assertions cover: it parses the
// compiled bytes, reports the page count, and draws one page frame per page.
const renderPage = vi.fn(() => ({ promise: Promise.resolve(), cancel: vi.fn() }));
const destroyDocument = vi.fn();
const getDocument = vi.fn(() => ({
  promise: Promise.resolve({
    numPages: 2,
    getPage: vi.fn(async () => ({
      getViewport: ({ scale }: { scale: number }) => ({ width: 595 * scale, height: 842 * scale }),
      render: renderPage,
      streamTextContent: vi.fn(),
    })),
  }),
  destroy: destroyDocument,
}));

vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: (...args: unknown[]) => getDocument(...(args as [])),
  TextLayer: class {
    render() {
      return Promise.resolve();
    }
  },
}));

const compile = vi.mocked(compileTexPdf);

/** A pane with a measurable width: `fit` derives the scale from it. */
function widePane() {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800);
}

describe('the LaTeX tab preview', () => {
  beforeEach(() => {
    compile.mockReset();
    getDocument.mockClear();
    renderPage.mockClear();
    destroyDocument.mockClear();
    compile.mockResolvedValue(new Blob(['%PDF-1.7'], { type: 'application/pdf' }));
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        disconnect() {}
      }
    );
    widePane();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('draws the engine-compiled PDF itself rather than handing it to the browser', async () => {
    // The app is embedded in a sandboxed iframe, where <object>/<embed> PDF
    // rendering is blocked outright. Every page must be drawn by pdf.js.
    const view = render(
      <TexPdfPreview
        resumeId="r-1"
        template="tex-classic"
        settings={DEFAULT_TEMPLATE_SETTINGS}
        revision={0}
      />
    );

    await waitFor(() => expect(screen.getByText('latex.previewPages:2')).toBeInTheDocument());
    expect(compile).toHaveBeenCalledWith('r-1', 'tex-classic', DEFAULT_TEMPLATE_SETTINGS);
    expect(getDocument).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(view.container.querySelectorAll('.pdf-page canvas')).toHaveLength(2)
    );
    expect(view.container.querySelector('object')).toBeNull();
    expect(view.container.querySelector('embed')).toBeNull();
    expect(view.container.querySelector('iframe')).toBeNull();
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

  it('keeps the visible pages until the recompile that replaces them lands', async () => {
    // The old renderer revoked its blob URL the moment a recompile started, so
    // the view pointed at freed bytes for the seconds the engine took.
    const view = render(
      <TexPdfPreview
        resumeId="r-1"
        template="tex-classic"
        settings={DEFAULT_TEMPLATE_SETTINGS}
        revision={0}
      />
    );
    await waitFor(() =>
      expect(view.container.querySelectorAll('.pdf-page canvas')).toHaveLength(2)
    );

    let release: (value: Blob) => void = () => {};
    compile.mockReturnValueOnce(
      new Promise<Blob>((resolve) => {
        release = resolve;
      })
    );
    view.rerender(
      <TexPdfPreview
        resumeId="r-1"
        template="tex-classic"
        settings={DEFAULT_TEMPLATE_SETTINGS}
        revision={1}
      />
    );

    await waitFor(() => expect(compile).toHaveBeenCalledTimes(2));
    expect(view.container.querySelectorAll('.pdf-page canvas')).toHaveLength(2);
    expect(destroyDocument).not.toHaveBeenCalled();

    await act(async () => {
      release(new Blob(['%PDF-1.7'], { type: 'application/pdf' }));
    });
    await waitFor(() => expect(destroyDocument).toHaveBeenCalledTimes(1));
  });

  it('explains a missing engine instead of rendering an empty frame', async () => {
    compile.mockRejectedValue(new TexUnavailableError('no engine'));

    const view = render(
      <TexPdfPreview
        resumeId="r-1"
        template="tex-classic"
        settings={DEFAULT_TEMPLATE_SETTINGS}
        revision={0}
      />
    );

    await waitFor(() => expect(screen.getByText('latex.noEngine')).toBeInTheDocument());
    expect(view.container.querySelector('.pdf-page')).toBeNull();
  });
});
