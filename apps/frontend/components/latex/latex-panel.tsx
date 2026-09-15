'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { useTranslations } from '@/lib/i18n';
import type { PageSize } from '@/lib/types/template-settings';
import {
  clearTexSource,
  compileTexPdf,
  getTexCapabilities,
  getTexSource,
  saveTexSource,
  downloadTexSource,
  TexCompileError,
  TexUnavailableError,
  type TexCapabilities,
  type TexTemplateId,
} from '@/lib/api/tex';

const TEMPLATES: TexTemplateId[] = ['tex-classic', 'tex-compact'];

interface LatexPanelProps {
  resumeId: string;
  /**
   * The template being edited. It comes from the one template picker in
   * Template & Formatting; this panel does not own the choice.
   */
  template: TexTemplateId;
  /** True when the picker's selection is an HTML template, so this tab is
   * showing `tex-classic` as a stand-in rather than the live selection. */
  htmlTemplateSelected: boolean;
  /** Used only by the notice that offers to switch to a LaTeX template. */
  onTemplateChange: (template: TexTemplateId) => void;
  /** The picker's page size — the one formatting control the engine reads. */
  pageSize: PageSize;
  /** Bumped by the parent after a document save, so a generated source refetches. */
  revision?: number;
  /** Invoked after a save or reset, which both land on the version timeline. */
  onSourceChanged?: () => void;
}

function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

/**
 * LaTeX source editor and PDF export.
 *
 * Two states, shown not implied: the source is either *generated* from the
 * document (and follows every edit) or an *override* the user owns (and the
 * document no longer touches it). Compilation may be unavailable — this panel
 * always offers the `.tex` download, which is the only export that never fails.
 */
export function LatexPanel({
  resumeId,
  template,
  htmlTemplateSelected,
  onTemplateChange,
  pageSize,
  revision = 0,
  onSourceChanged,
}: LatexPanelProps) {
  const { t } = useTranslations();
  const [source, setSource] = useState('');
  const [serverSource, setServerSource] = useState('');
  const [isOverride, setIsOverride] = useState(false);
  const [capabilities, setCapabilities] = useState<TexCapabilities | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'saving' | 'compiling' | 'resetting' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [compileLog, setCompileLog] = useState<string | null>(null);
  const [pendingReset, setPendingReset] = useState(false);
  const isDirty = source !== serverSource;

  useEffect(() => {
    let cancelled = false;
    getTexCapabilities()
      .then((value) => {
        if (!cancelled) setCapabilities(value);
      })
      .catch(() => {
        if (!cancelled) setCapabilities({ engine: null, can_compile: false, templates: TEMPLATES });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const load = useCallback(
    async (nextTemplate: TexTemplateId) => {
      setLoading(true);
      setError(null);
      try {
        const result = await getTexSource(resumeId, { template: nextTemplate, pageSize });
        setSource(result.source);
        setServerSource(result.source);
        setIsOverride(result.is_override);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : t('latex.errors.load'));
      } finally {
        setLoading(false);
      }
    },
    [resumeId, pageSize, t]
  );

  useEffect(() => {
    void load(template);
    // `revision` participates so a document save refreshes generated source.
  }, [load, template, revision]);

  const handleSave = async () => {
    setBusy('saving');
    setError(null);
    try {
      const result = await saveTexSource(resumeId, source);
      setServerSource(result.source);
      setIsOverride(true);
      onSourceChanged?.();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : t('latex.errors.save'));
    } finally {
      setBusy(null);
    }
  };

  const handleReset = async () => {
    setPendingReset(false);
    setBusy('resetting');
    setError(null);
    try {
      const result = await clearTexSource(resumeId, template, pageSize);
      setSource(result.source);
      setServerSource(result.source);
      setIsOverride(false);
      onSourceChanged?.();
    } catch (resetError) {
      setError(resetError instanceof Error ? resetError.message : t('latex.errors.reset'));
    } finally {
      setBusy(null);
    }
  };

  const handleDownloadSource = async () => {
    setError(null);
    try {
      download(await downloadTexSource(resumeId, template, pageSize), `resume-${template}.tex`);
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : t('latex.errors.load'));
    }
  };

  const handleCompile = async () => {
    setBusy('compiling');
    setError(null);
    setCompileLog(null);
    try {
      download(await compileTexPdf(resumeId, template, pageSize), `resume-${template}.pdf`);
    } catch (compileError) {
      if (compileError instanceof TexCompileError) {
        setError(compileError.message);
        setCompileLog(compileError.log);
      } else if (compileError instanceof TexUnavailableError) {
        setError(compileError.message);
      } else {
        setError(compileError instanceof Error ? compileError.message : t('latex.errors.compile'));
      }
    } finally {
      setBusy(null);
    }
  };

  const canCompile = capabilities?.can_compile ?? false;
  const lineCount = useMemo(() => source.split('\n').length, [source]);

  return (
    <div className="flex flex-col h-full gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs uppercase text-steel-grey">{t('latex.template')}</span>
        <span className="border-2 border-black bg-black px-3 py-1 font-mono text-xs uppercase text-white">
          {t(`latex.templates.${template}`)}
        </span>
        <span className="ml-auto font-mono text-xs uppercase text-steel-grey">
          {isOverride ? t('latex.state.edited') : t('latex.state.generated')}
        </span>
      </div>

      {htmlTemplateSelected && (
        <div className="flex flex-wrap items-center gap-2 border-2 border-black bg-paper-tint px-3 py-2">
          <p className="font-mono text-xs">{t('latex.htmlTemplateNotice')}</p>
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            onClick={() => onTemplateChange('tex-classic')}
          >
            {t('latex.templates.tex-classic')}
          </Button>
        </div>
      )}

      {isOverride && (
        <p className="border-2 border-black bg-alert-orange/10 px-3 py-2 font-mono text-xs">
          {t('latex.overrideNotice')}
        </p>
      )}

      {!canCompile && capabilities !== null && (
        <p className="border-2 border-black bg-paper-tint px-3 py-2 font-mono text-xs">
          {t('latex.noEngine')}
        </p>
      )}

      {error && (
        <div className="border-2 border-alert-red bg-white px-3 py-2">
          <p className="font-mono text-xs text-alert-red">{error}</p>
          {compileLog && (
            <pre className="mt-2 max-h-40 overflow-auto bg-paper-tint p-2 font-mono text-[11px] whitespace-pre-wrap">
              {compileLog}
            </pre>
          )}
        </div>
      )}

      <textarea
        value={source}
        onChange={(event) => setSource(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.stopPropagation();
        }}
        spellCheck={false}
        disabled={loading}
        aria-label={t('latex.sourceLabel')}
        className="flex-1 min-h-64 w-full resize-none border-2 border-black bg-white p-3 font-mono text-xs leading-relaxed rounded-none focus:outline-none focus:ring-0 focus:border-hyper-blue disabled:opacity-50"
      />

      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-steel-grey">
          {t('latex.lineCount', { count: lineCount })}
        </span>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleDownloadSource}
            disabled={busy !== null || loading}
          >
            {t('latex.downloadTex')}
          </Button>
          {isOverride && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPendingReset(true)}
              disabled={busy !== null}
            >
              {t('latex.reset')}
            </Button>
          )}
          <Button size="sm" onClick={handleSave} disabled={!isDirty || busy !== null || loading}>
            {busy === 'saving' ? t('latex.saving') : t('latex.save')}
          </Button>
          <Button
            size="sm"
            onClick={handleCompile}
            disabled={!canCompile || busy !== null || loading}
            title={canCompile ? undefined : t('latex.noEngine')}
          >
            {busy === 'compiling' ? t('latex.compiling') : t('latex.downloadPdf')}
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={pendingReset}
        onOpenChange={(open) => !open && setPendingReset(false)}
        title={t('latex.resetConfirmTitle')}
        description={t('latex.resetConfirmBody')}
        confirmLabel={t('latex.reset')}
        variant="danger"
        onConfirm={handleReset}
      />
    </div>
  );
}
