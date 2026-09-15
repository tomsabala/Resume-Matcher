import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TexPdfPreview } from '@/components/latex/tex-pdf-preview';
import { compileTexPdf, TexUnavailableError } from '@/lib/api/tex';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (key: string) => key }) }));

vi.mock('@/lib/api/tex', () => {
  class TexUnavailableError extends Error {}
  class TexCompileError extends Error {
    log = '';
  }
  return { compileTexPdf: vi.fn(), TexUnavailableError, TexCompileError };
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

  it('shows the engine-compiled PDF rather than a browser approximation', async () => {
    render(<TexPdfPreview resumeId="r-1" template="tex-classic" pageSize="A4" revision={0} />);

    await waitFor(() => expect(screen.getByLabelText('latex.previewLabel')).toBeInTheDocument());
    expect(compile).toHaveBeenCalledWith('r-1', 'tex-classic', 'A4');
    expect(screen.getByLabelText('latex.previewLabel')).toHaveAttribute('data', 'blob:compiled');
  });

  it('recompiles when the template the source editor shows changes', async () => {
    const view = render(
      <TexPdfPreview resumeId="r-1" template="tex-classic" pageSize="A4" revision={0} />
    );
    await waitFor(() => expect(compile).toHaveBeenCalledTimes(1));

    view.rerender(
      <TexPdfPreview resumeId="r-1" template="tex-compact" pageSize="A4" revision={0} />
    );

    await waitFor(() => expect(compile).toHaveBeenLastCalledWith('r-1', 'tex-compact', 'A4'));
  });

  it('recompiles when the saved source changes', async () => {
    const view = render(
      <TexPdfPreview resumeId="r-1" template="tex-classic" pageSize="A4" revision={0} />
    );
    await waitFor(() => expect(compile).toHaveBeenCalledTimes(1));

    view.rerender(
      <TexPdfPreview resumeId="r-1" template="tex-classic" pageSize="A4" revision={1} />
    );

    await waitFor(() => expect(compile).toHaveBeenCalledTimes(2));
  });

  it('explains a missing engine instead of rendering an empty frame', async () => {
    compile.mockRejectedValue(new TexUnavailableError('no engine'));

    render(<TexPdfPreview resumeId="r-1" template="tex-classic" pageSize="A4" revision={0} />);

    await waitFor(() => expect(screen.getByText('latex.noEngine')).toBeInTheDocument());
    expect(screen.queryByLabelText('latex.previewLabel')).not.toBeInTheDocument();
  });
});
