'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Input } from '@/components/ui/input';
import { useTranslations } from '@/lib/i18n';
import {
  deleteVersion,
  listVersions,
  restoreVersion,
  updateVersion,
  type VersionSummary,
} from '@/lib/api/versions';

const PAGE_SIZE = 25;

interface VersionTimelineProps {
  resumeId: string;
  /** Bumped by the parent after it saves, so the timeline refetches. */
  revision?: number;
  /** Invoked after a restore lands, so the editor can reload the document. */
  onRestored?: (version: VersionSummary) => void;
  /**
   * Opens the diff surface for this version against the current one. Without
   * it the row links to the Compare screen itself, which is the same
   * comparison as a shareable URL.
   */
  onCompare?: (version: VersionSummary) => void;
}

/**
 * Append-only history of one resume.
 *
 * A 12px status square carries the row's state — Signal Green for the current
 * version, Ink for a pinned one, Steel Grey otherwise — per the Swiss palette.
 */
export function VersionTimeline({
  resumeId,
  revision = 0,
  onRestored,
  onCompare,
}: VersionTimelineProps) {
  const { t, locale } = useTranslations();
  const router = useRouter();
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [labelDraft, setLabelDraft] = useState('');
  const [pendingRestore, setPendingRestore] = useState<VersionSummary | null>(null);
  const [isRestoring, setIsRestoring] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const page = await listVersions(resumeId, { limit: PAGE_SIZE });
      setVersions(page.versions);
      setCursor(page.next_cursor);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t('versions.loadFailed'));
    } finally {
      setIsLoading(false);
    }
  }, [resumeId, t]);

  useEffect(() => {
    void load();
  }, [load, revision]);

  const loadOlder = async () => {
    if (!cursor) return;
    try {
      const page = await listVersions(resumeId, { limit: PAGE_SIZE, cursor });
      setVersions((rows) => [...rows, ...page.versions]);
      setCursor(page.next_cursor);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t('versions.loadFailed'));
    }
  };

  const applyUpdate = (updated: VersionSummary) =>
    setVersions((rows) =>
      rows.map((row) => (row.version_id === updated.version_id ? updated : row))
    );

  const commitLabel = async (version: VersionSummary) => {
    setEditingId(null);
    const next = labelDraft.trim();
    if (next === (version.label ?? '')) return;
    applyUpdate(await updateVersion(version.version_id, { label: next || null }));
  };

  const togglePin = async (version: VersionSummary) => {
    applyUpdate(await updateVersion(version.version_id, { is_pinned: !version.is_pinned }));
  };

  const remove = async (version: VersionSummary) => {
    try {
      await deleteVersion(version.version_id);
      setVersions((rows) => rows.filter((row) => row.version_id !== version.version_id));
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : t('versions.deleteFailed'));
    }
  };

  const confirmRestore = async () => {
    if (!pendingRestore) return;
    setIsRestoring(true);
    try {
      const restored = await restoreVersion(resumeId, pendingRestore.version_id);
      setPendingRestore(null);
      await load();
      onRestored?.(restored);
    } catch (restoreError) {
      setError(restoreError instanceof Error ? restoreError.message : t('versions.restoreFailed'));
    } finally {
      setIsRestoring(false);
    }
  };

  const formatTimestamp = (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString(locale, {
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const squareClass = (version: VersionSummary) => {
    if (version.is_head) return 'bg-green-700';
    if (version.is_pinned) return 'bg-black';
    return 'bg-steel-grey';
  };

  // Base is the older version, head the resume as it stands: "what changed
  // since this point" is the question a timeline row asks.
  const compare = (version: VersionSummary) => {
    if (onCompare) {
      onCompare(version);
      return;
    }
    router.push(`/compare?base=version:${version.version_id}&head=resume:${resumeId}`);
  };

  return (
    <section className="border-2 border-black bg-white shadow-sw-default rounded-none">
      <header className="flex items-center justify-between border-b-2 border-black px-4 py-2">
        <h2 className="font-mono text-xs font-bold uppercase tracking-wider">
          {t('versions.title')}
        </h2>
      </header>

      {error && (
        <p className="border-b border-black px-4 py-2 font-mono text-xs uppercase tracking-wider text-red-600">
          {error}
        </p>
      )}

      {!isLoading && versions.length === 0 && (
        <p className="px-4 py-6 text-sm text-ink-soft">{t('versions.empty')}</p>
      )}

      <ol>
        {versions.map((version) => (
          <li
            key={version.version_id}
            className="flex flex-wrap items-center gap-3 border-b border-black px-4 py-3 last:border-b-0"
          >
            <span aria-hidden="true" className={`h-3 w-3 shrink-0 ${squareClass(version)}`} />
            <span className="font-mono text-xs font-bold uppercase tracking-wider">
              {t(`versions.origin.${version.origin}`)}
            </span>
            <span className="font-mono text-xs text-steel-grey">
              {formatTimestamp(version.created_at)}
            </span>

            {editingId === version.version_id ? (
              <Input
                autoFocus
                value={labelDraft}
                onChange={(event) => setLabelDraft(event.target.value)}
                onBlur={() => void commitLabel(version)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void commitLabel(version);
                  if (event.key === 'Escape') setEditingId(null);
                }}
                placeholder={t('versions.labelPlaceholder')}
                aria-label={t('versions.labelPlaceholder')}
                className="h-7 max-w-[14rem] flex-1 text-sm"
              />
            ) : (
              <button
                type="button"
                onClick={() => {
                  setEditingId(version.version_id);
                  setLabelDraft(version.label ?? '');
                }}
                className="flex-1 truncate text-left text-sm hover:underline"
              >
                {version.label || t('versions.labelPlaceholder')}
              </button>
            )}

            {version.is_head && (
              <span className="border border-black px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider">
                {t('versions.current')}
              </span>
            )}

            <div className="flex items-center gap-2">
              {!version.is_head && (
                <Button variant="outline" size="sm" onClick={() => compare(version)}>
                  {t('versions.compare')}
                </Button>
              )}
              <Button variant="outline" size="sm" onClick={() => void togglePin(version)}>
                {version.is_pinned ? t('versions.unpin') : t('versions.pin')}
              </Button>
              {!version.is_head && (
                <>
                  <Button size="sm" onClick={() => setPendingRestore(version)}>
                    {t('versions.restore')}
                  </Button>
                  {!version.is_pinned && (
                    <Button variant="outline" size="sm" onClick={() => void remove(version)}>
                      {t('versions.delete')}
                    </Button>
                  )}
                </>
              )}
            </div>
          </li>
        ))}
      </ol>

      {cursor && (
        <div className="border-t-2 border-black px-4 py-2">
          <Button variant="outline" size="sm" onClick={() => void loadOlder()}>
            {t('versions.loadMore')}
          </Button>
        </div>
      )}

      <ConfirmDialog
        open={pendingRestore !== null}
        onOpenChange={(open) => !open && setPendingRestore(null)}
        title={t('versions.restoreConfirmTitle')}
        description={t('versions.restoreConfirmBody')}
        confirmLabel={t('versions.restore')}
        onConfirm={() => void confirmRestore()}
        confirmDisabled={isRestoring}
      />
    </section>
  );
}
