'use client';

import React from 'react';
import { useTranslations } from '@/lib/i18n';
import type { DiffStats } from '@/lib/api/diff';

/** Counter order, which is also reading order: sections, entries, leaves. */
const COUNTERS: Array<keyof DiffStats> = [
  'sections_added',
  'sections_removed',
  'sections_renamed',
  'sections_moved',
  'entries_added',
  'entries_removed',
  'entries_modified',
  'entries_moved',
  'bullets_added',
  'bullets_removed',
  'bullets_modified',
  'tags_added',
  'tags_removed',
];

export interface DiffStatsBarProps {
  stats: DiffStats;
}

/**
 * The comparison's counts as mono counters.
 *
 * Zero counters are omitted: a bar that lists thirteen numbers, eleven of them
 * zero, is a table nobody reads.
 */
export function DiffStatsBar({ stats }: DiffStatsBarProps) {
  const { t } = useTranslations();
  const present = COUNTERS.filter((counter) => stats[counter] > 0);

  return (
    <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 border-2 border-black bg-white px-4 py-2">
      <span className="font-mono text-xs font-bold tracking-wider uppercase">
        {t('diff.stats.totalChanges')}
        <span className="ml-2 text-sm">{stats.total_changes}</span>
      </span>
      {present.length === 0 ? (
        <span className="font-mono text-xs tracking-wider text-steel-grey uppercase">
          {t('diff.noChanges')}
        </span>
      ) : (
        present.map((counter) => (
          <span
            key={counter}
            className="font-mono text-xs tracking-wider text-steel-grey uppercase"
          >
            {t(`diff.stats.${counter}`)}
            <span className="ml-2 text-sm text-ink">{stats[counter]}</span>
          </span>
        ))
      )}
    </div>
  );
}

export default DiffStatsBar;
