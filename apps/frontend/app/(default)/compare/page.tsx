'use client';

import React, { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import ArrowLeft from 'lucide-react/dist/esm/icons/arrow-left';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import { useSearchParams } from 'next/navigation';
import { DiffView } from '@/components/diff/diff-view';
import { compareDocuments, parseRefToken, type DiffRef, type DocumentDiff } from '@/lib/api/diff';
import { useTranslations } from '@/lib/i18n';

/**
 * Compare two documents named by the query string.
 *
 * `?base=resume:<id>|version:<id>&head=...` — a comparison is therefore a
 * linkable thing: the version timeline and the dashboard's resume selection
 * both just navigate here.
 */
function CompareContent() {
  const { t } = useTranslations();
  const searchParams = useSearchParams();
  const baseToken = searchParams.get('base');
  const headToken = searchParams.get('head');

  const base = useMemo(() => parseRefToken(baseToken), [baseToken]);
  const head = useMemo(() => parseRefToken(headToken), [headToken]);

  const [diff, setDiff] = useState<DocumentDiff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!base || !head) return;
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    compareDocuments(base, head)
      .then((result) => {
        if (!cancelled) setDiff(result);
      })
      .catch((failure: unknown) => {
        if (cancelled) return;
        setDiff(null);
        setError(failure instanceof Error ? failure.message : t('compare.loadFailed'));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [base, head, t]);

  const describe = (ref: DiffRef | null) => {
    if (!ref) return '\u2014';
    return ref.version_id
      ? t('compare.versionRef', { id: ref.version_id })
      : t('compare.resumeRef', { id: ref.resume_id ?? '' });
  };

  return (
    <div className="min-h-screen w-full bg-background px-4 pt-6 pb-16 md:px-8">
      <div className="w-full max-w-[96rem]">
        <Link
          href="/dashboard"
          className="mb-3 inline-flex items-center gap-1 font-mono text-xs uppercase tracking-wider text-ink-soft hover:text-primary"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {t('compare.back')}
        </Link>

        <header className="border-2 border-black bg-white px-6 pt-6 pb-8 shadow-sw-default">
          <h1 className="font-serif text-3xl font-bold uppercase tracking-tight">
            {t('compare.title')}
          </h1>
          <p className="mt-2 font-mono text-xs uppercase tracking-wider text-steel-grey">
            {'// '}
            {t('compare.subtitle')}
          </p>

          <dl className="mt-6 flex flex-wrap gap-x-12 gap-y-3">
            <div>
              <dt className="font-mono text-xs uppercase tracking-wider text-steel-grey">
                {t('diff.baseLabel')}
              </dt>
              <dd className="font-mono text-sm">{describe(base)}</dd>
            </div>
            <div>
              <dt className="font-mono text-xs uppercase tracking-wider text-steel-grey">
                {t('diff.headLabel')}
              </dt>
              <dd className="font-mono text-sm">{describe(head)}</dd>
            </div>
          </dl>
        </header>

        {!base || !head ? (
          <p
            role="alert"
            className="mt-6 border-2 border-red-600 bg-white px-4 py-3 font-mono text-xs uppercase tracking-wider text-red-600"
          >
            {t('compare.invalidRefs')}
          </p>
        ) : (
          <div className="mt-6">
            {error && (
              <p
                role="alert"
                className="mb-6 border-2 border-red-600 bg-white px-4 py-3 font-mono text-xs text-red-600"
              >
                {error}
              </p>
            )}
            {isLoading && (
              <p className="flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-steel-grey">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('compare.loading')}
              </p>
            )}
            {diff && !isLoading && <DiffView diff={diff} />}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={null}>
      <CompareContent />
    </Suspense>
  );
}
