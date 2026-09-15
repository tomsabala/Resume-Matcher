'use client';

import { useState, useEffect, useMemo } from 'react';
import { AlertTriangle, CheckCircle, X, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useTranslations } from '@/lib/i18n';
import { DiffView } from '@/components/diff/diff-view';
import { selectablePaths } from '@/components/diff/paths';
import type { DocumentDiff } from '@/lib/api/diff';

interface DiffPreviewModalProps {
  isOpen: boolean;
  isConfirming?: boolean;
  onClose: () => void;
  onReject: () => void;
  /**
   * `null` accepts the whole proposal, including structural changes no single
   * row owns; an array takes only the named content leaves.
   */
  onConfirm: (acceptedPaths: string[] | null) => void;
  diff?: DocumentDiff | null;
  errorMessage?: string;
}

export function DiffPreviewModal({
  isOpen,
  isConfirming = false,
  onClose,
  onReject,
  onConfirm,
  diff,
  errorMessage,
}: DiffPreviewModalProps) {
  const { t } = useTranslations();

  // Elapsed timer while confirming
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    setElapsed(0);
    if (!isConfirming) return;
    const timer = window.setInterval(() => setElapsed((seconds) => seconds + 1), 1000);
    return () => clearInterval(timer);
  }, [isConfirming]);

  // Everything is ticked by default, so the plain "accept the tailoring" flow
  // is one click and behaves exactly as it did before partial accept existed.
  const allPaths = useMemo(() => (diff ? selectablePaths(diff) : []), [diff]);
  const [accepted, setAccepted] = useState<string[]>(allPaths);

  useEffect(() => {
    setAccepted(allPaths);
  }, [allPaths]);

  if (!diff) {
    return (
      <Dialog
        open={isOpen}
        onOpenChange={(open) => {
          if (!open && !isConfirming) {
            onClose();
          }
        }}
      >
        <DialogContent className="max-w-5xl max-h-[90vh] overflow-hidden flex flex-col p-6 bg-background border-2 border-black shadow-sw-lg">
          <DialogHeader className="border-b-2 border-black pb-4 bg-white -mx-6 -mt-6 px-6 pt-6">
            <DialogTitle className="font-serif text-2xl font-bold uppercase tracking-tight">
              {t('tailor.missingDiffDialog.title')}
            </DialogTitle>
          </DialogHeader>

          <div className="mt-6 border-2 border-black bg-white p-4 font-mono text-xs text-ink-soft">
            {t('tailor.missingDiffDialog.description')}
          </div>
          <div className="mt-3 flex items-center gap-2 font-mono text-xs text-amber-700">
            <AlertTriangle className="w-4 h-4" />
            <span>{t('tailor.missingDiffDialog.confirmLabel')}</span>
          </div>

          <div className="flex justify-end items-center gap-3 pt-4 border-t-2 border-black bg-white -mx-6 -mb-6 px-6 py-4">
            <Button variant="outline" onClick={onClose} disabled={isConfirming} className="gap-2">
              {t('common.cancel')}
            </Button>
            <Button
              variant="warning"
              onClick={() => onConfirm(null)}
              disabled={isConfirming}
              className="gap-2"
            >
              {isConfirming ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t('common.saving')}
                </>
              ) : (
                t('tailor.missingDiffDialog.confirmLabel')
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  const isWholePreview = accepted.length === allPaths.length;

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open && !isConfirming) {
          onClose();
        }
      }}
    >
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-hidden flex flex-col p-6 bg-background border-2 border-black shadow-sw-lg">
        <DialogHeader className="border-b-2 border-black pb-4 bg-white -mx-6 -mt-6 px-6 pt-6">
          <DialogTitle className="font-serif text-2xl font-bold uppercase tracking-tight">
            {t('tailor.diffModal.title')}
          </DialogTitle>
          <p className="font-mono text-xs text-ink-soft mt-2">
            {'// '}
            {t('tailor.diffModal.subtitle')}
          </p>
        </DialogHeader>

        {errorMessage && (
          <div className="mt-4 border-2 border-red-600 bg-white p-3 font-mono text-xs text-red-600">
            {errorMessage}
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto mt-4">
          <DiffView diff={diff} acceptedPaths={accepted} onAcceptedPathsChange={setAccepted} />
        </div>

        <div className="flex justify-between items-center pt-4 border-t-2 border-black bg-white -mx-6 -mb-6 px-6 py-4">
          <Button variant="outline" onClick={onReject} disabled={isConfirming} className="gap-2">
            <X className="w-4 h-4" />
            {t('tailor.diffModal.rejectButton')}
          </Button>
          <div className="flex items-center gap-3">
            {allPaths.length > 0 && (
              <span className="font-mono text-xs uppercase tracking-wider text-steel-grey">
                {accepted.length === 0
                  ? t('tailor.diffModal.noSelection')
                  : t('tailor.diffModal.acceptingCount', {
                      count: accepted.length,
                      total: allPaths.length,
                    })}
              </span>
            )}
            {isConfirming && elapsed > 0 && (
              <span className="font-mono text-xs text-steel-grey">{elapsed}s</span>
            )}
            <Button
              onClick={() => onConfirm(isWholePreview ? null : accepted)}
              disabled={isConfirming || (allPaths.length > 0 && accepted.length === 0)}
              className="gap-2 bg-success hover:bg-green-800"
            >
              {isConfirming ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t('common.saving')}
                </>
              ) : (
                <>
                  <CheckCircle className="w-4 h-4" />
                  {t('tailor.diffModal.confirmButton')}
                </>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
