'use client';

import { useCallback, useEffect, useState } from 'react';
import AlertTriangle from 'lucide-react/dist/esm/icons/alert-triangle';
import { Button } from '@/components/ui/button';
import { useTranslations } from '@/lib/i18n';
import {
  dismissAIFailures,
  fetchAIFailures,
  type AIFailure,
  type AIFailureKind,
} from '@/lib/api/diagnostics';

/** How often the panel re-reads the tail, so a failure appears without a reload. */
const POLL_INTERVAL_MS = 30_000;

const KIND_LABEL_KEY: Record<AIFailureKind, string> = {
  truncated: 'dashboard.aiFailures.kinds.truncated',
  malformed: 'dashboard.aiFailures.kinds.malformed',
  empty: 'dashboard.aiFailures.kinds.empty',
  invalid: 'dashboard.aiFailures.kinds.invalid',
  provider: 'dashboard.aiFailures.kinds.provider',
};

/**
 * Recent AI failures, shown only when there are any.
 *
 * A model that answers with truncated JSON, or a provider that rejects the
 * request, used to surface as a generic "please try again": the reason lived
 * in the server log alone. This states the reason, and for the budget case
 * says what to change.
 */
export function AIFailurePanel({ revision = 0 }: { revision?: number }) {
  const { t, locale } = useTranslations();
  const [failures, setFailures] = useState<AIFailure[]>([]);
  const [isDismissing, setIsDismissing] = useState(false);

  const load = useCallback(async () => {
    try {
      setFailures(await fetchAIFailures());
    } catch {
      // Diagnostics must never break the dashboard they annotate.
      setFailures([]);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [load, revision]);

  const handleDismiss = async () => {
    setIsDismissing(true);
    try {
      await dismissAIFailures();
      setFailures([]);
    } catch {
      await load();
    } finally {
      setIsDismissing(false);
    }
  };

  if (failures.length === 0) return null;

  return (
    <section
      role="alert"
      aria-label={t('dashboard.aiFailures.title')}
      className="border-2 border-warning bg-amber-50 p-4 shadow-sw-default"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" />
          <div>
            <p className="font-mono text-sm font-bold uppercase tracking-wider text-amber-800">
              {t('dashboard.aiFailures.title')}
            </p>
            <p className="mt-1 font-mono text-xs text-amber-800">
              {t('dashboard.aiFailures.summary', { count: failures.length })}
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={handleDismiss} disabled={isDismissing}>
          {t('dashboard.aiFailures.dismiss')}
        </Button>
      </div>

      <ul className="mt-4 space-y-2">
        {failures.map((failure) => (
          <li key={failure.id} className="border border-black bg-white p-3">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="font-mono text-xs font-bold uppercase">
                {t(KIND_LABEL_KEY[failure.kind] ?? KIND_LABEL_KEY.provider)}
              </span>
              <span className="font-mono text-[11px] uppercase text-steel-grey">
                {failure.operation}
              </span>
              <time dateTime={failure.at} className="ml-auto font-mono text-[11px] text-steel-grey">
                {new Date(failure.at).toLocaleString(locale)}
              </time>
            </div>
            <p className="mt-1 font-mono text-[11px] break-words text-ink-soft">{failure.detail}</p>
            <div className="mt-1 flex flex-wrap gap-x-4 font-mono text-[11px] text-steel-grey">
              {failure.model && <span>{failure.model}</span>}
              {failure.max_tokens != null && (
                <span>{t('dashboard.aiFailures.budget', { tokens: failure.max_tokens })}</span>
              )}
              {failure.attempts != null && (
                <span>{t('dashboard.aiFailures.attempts', { count: failure.attempts })}</span>
              )}
            </div>
            {failure.kind === 'truncated' && (
              <p className="mt-2 font-mono text-[11px] text-amber-800">
                {t('dashboard.aiFailures.hintTruncated')}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
