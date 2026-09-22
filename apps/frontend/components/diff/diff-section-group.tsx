'use client';

import React from 'react';
import ChevronDown from 'lucide-react/dist/esm/icons/chevron-down';
import ChevronRight from 'lucide-react/dist/esm/icons/chevron-right';
import { useTranslations } from '@/lib/i18n';
import type { SectionStatus } from '@/lib/api/diff';

/** 12px status square — squares, never dots, per the Swiss palette. */
const SQUARE_CLASS: Record<SectionStatus, string> = {
  added: 'bg-green-700',
  removed: 'bg-red-600',
  renamed: 'bg-orange-500',
  modified: 'bg-orange-500',
  moved: 'bg-blue-700',
  unchanged: 'bg-steel-grey',
};

export interface DiffSectionGroupProps {
  status: SectionStatus;
  /** Heading as the base document had it; the only heading a removal has. */
  baseHeading: string | null;
  /** Heading as the head document has it. */
  headHeading: string | null;
  rowCount: number;
  isExpanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

/**
 * One section of a diff, under a sticky header.
 *
 * A renamed section shows both headings — the rename is the change, so hiding
 * either side would hide it.
 */
export function DiffSectionGroup({
  status,
  baseHeading,
  headHeading,
  rowCount,
  isExpanded,
  onToggle,
  children,
}: DiffSectionGroupProps) {
  const { t } = useTranslations();
  const fallback = t('diff.untitledSection');
  const heading =
    status === 'renamed'
      ? `${baseHeading || fallback} \u2192 ${headHeading || fallback}`
      : headHeading || baseHeading || fallback;

  return (
    <section className="border-2 border-black bg-white">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isExpanded}
        className="sticky top-14 z-10 lg:top-0 flex w-full flex-wrap items-center gap-2 border-b-2 border-black bg-white px-3 py-2 text-left"
      >
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 shrink-0" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0" />
        )}
        <span aria-hidden="true" className={`h-3 w-3 shrink-0 ${SQUARE_CLASS[status]}`} />
        <span className="min-w-0 flex-1 truncate font-mono text-xs font-bold tracking-wider uppercase">
          {heading}
        </span>
        <span className="flex w-full items-center gap-2 sm:w-auto">
          <span className="shrink-0 font-mono text-xs tracking-wider text-steel-grey uppercase">
            {t(`diff.sectionStatus.${status}`)}
          </span>
          <span className="shrink-0 font-mono text-xs text-steel-grey">
            {t('diff.rowCount', { count: rowCount })}
          </span>
        </span>
      </button>

      {isExpanded && <div>{children}</div>}
    </section>
  );
}

export default DiffSectionGroup;
