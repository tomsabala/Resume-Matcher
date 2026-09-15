'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from '@/lib/i18n';
import { compileTexPdf, TexCompileError, TexUnavailableError } from '@/lib/api/tex';
import type { TexTemplateId } from '@/lib/api/tex';

interface TexPdfPreviewProps {
  resumeId: string;
  template: TexTemplateId;
  /** Bumped by the parent after a save or reset, so the compile reruns. */
  revision: number;
}

/**
 * Why a failure is stored rather than its message: translating inside the
 * effect would put `t` in its dependency list, and `t` is a fresh identity
 * every render — the preview would recompile in a loop.
 */
type Failure =
  | { kind: 'unavailable' }
  | { kind: 'compile'; message: string; log: string }
  | { kind: 'other'; message: string | null };

/**
 * The engine-compiled PDF, shown beside its source.
 *
 * The LaTeX tab used to preview the browser-rendered HTML template, which is a
 * different renderer with different fonts and metrics: what the tab showed was
 * never what its Download PDF produced. This compiles the same source the
 * download does, so the preview is the artifact.
 */
export function TexPdfPreview({ resumeId, template, revision }: TexPdfPreviewProps) {
  const { t } = useTranslations();
  const [url, setUrl] = useState<string | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [compiling, setCompiling] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;

    setCompiling(true);
    setFailure(null);

    compileTexPdf(resumeId, template)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((compileError: unknown) => {
        if (cancelled) return;
        setUrl(null);
        if (compileError instanceof TexCompileError) {
          setFailure({ kind: 'compile', message: compileError.message, log: compileError.log });
        } else if (compileError instanceof TexUnavailableError) {
          setFailure({ kind: 'unavailable' });
        } else {
          setFailure({
            kind: 'other',
            message: compileError instanceof Error ? compileError.message : null,
          });
        }
      })
      .finally(() => {
        if (!cancelled) setCompiling(false);
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [resumeId, template, revision]);

  if (failure) {
    return (
      <div className="border-2 border-alert-red bg-white p-3">
        <p className="font-mono text-xs text-alert-red">
          {failure.kind === 'unavailable'
            ? t('latex.noEngine')
            : failure.message || t('latex.errors.compile')}
        </p>
        {failure.kind === 'compile' && failure.log && (
          <pre className="mt-2 max-h-96 overflow-auto bg-paper-tint p-2 font-mono text-[11px] whitespace-pre-wrap">
            {failure.log}
          </pre>
        )}
      </div>
    );
  }

  if (compiling && !url) {
    return (
      <div className="border-2 border-black bg-white p-3 font-mono text-xs uppercase text-steel-grey">
        {t('latex.previewCompiling')}
      </div>
    );
  }

  if (!url) return null;

  return (
    <object
      data={url}
      type="application/pdf"
      aria-label={t('latex.previewLabel')}
      className="h-full w-full border-2 border-black bg-white"
    />
  );
}
