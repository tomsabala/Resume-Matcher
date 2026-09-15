'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { useTranslations } from '@/lib/i18n';
import type { DiffRow, DocumentDiff } from '@/lib/api/diff';
import { DiffRowLine } from './diff-row';
import { DiffSectionGroup } from './diff-section-group';
import { DiffStatsBar } from './diff-stats-bar';
import { isSelectableRow, selectablePaths } from './paths';

export type DiffViewMode = 'unified' | 'split';

/** A run of unchanged rows this long collapses behind an expander. */
const UNCHANGED_RUN_LIMIT = 3;

interface RowChunk {
  /** Index of the chunk's first row, which is also its stable identity. */
  start: number;
  collapsible: boolean;
  rows: DiffRow[];
}

/**
 * Splits rows into alternating changed and unchanged runs.
 *
 * Only long unchanged runs are worth hiding; a one- or two-row gap between two
 * changes reads as context, and collapsing it costs more clicks than it saves.
 */
function toChunks(rows: DiffRow[]): RowChunk[] {
  const chunks: RowChunk[] = [];
  let index = 0;
  while (index < rows.length) {
    const unchanged = rows[index].status === 'unchanged';
    let end = index;
    while (end < rows.length && (rows[end].status === 'unchanged') === unchanged) end += 1;
    const run = rows.slice(index, end);
    chunks.push({
      start: index,
      collapsible: unchanged && run.length >= UNCHANGED_RUN_LIMIT,
      rows: run,
    });
    index = end;
  }
  return chunks;
}

export interface DiffRowsProps {
  rows: DiffRow[];
  view?: DiffViewMode;
  /** Paths currently accepted; only meaningful with `onTogglePath`. */
  selectedPaths?: ReadonlySet<string>;
  /** Supplying this renders a checkbox on every selectable row. */
  onTogglePath?: (path: string, next: boolean) => void;
}

/**
 * A flat list of diff rows, with long unchanged runs collapsed.
 *
 * Used directly wherever a feature compares two lists rather than two whole
 * documents — the AI regenerate preview — and by `DiffView` per section.
 */
export function DiffRows({ rows, view = 'unified', selectedPaths, onTogglePath }: DiffRowsProps) {
  const { t } = useTranslations();
  const chunks = useMemo(() => toChunks(rows), [rows]);
  const [expandedRuns, setExpandedRuns] = useState<Record<number, boolean>>({});

  useEffect(() => {
    setExpandedRuns({});
  }, [rows]);

  return (
    <div>
      {chunks.map((chunk) => {
        const isExpanded = expandedRuns[chunk.start] ?? false;
        const body = chunk.rows.map((row, offset) => (
          <DiffRowLine
            key={`${chunk.start + offset}-${row.path}`}
            row={row}
            view={view}
            checked={selectedPaths?.has(row.path) ?? false}
            onToggle={onTogglePath && isSelectableRow(row) ? onTogglePath : undefined}
          />
        ));

        if (!chunk.collapsible) return <div key={chunk.start}>{body}</div>;

        return (
          <div key={chunk.start}>
            <button
              type="button"
              aria-expanded={isExpanded}
              onClick={() =>
                setExpandedRuns((current) => ({ ...current, [chunk.start]: !isExpanded }))
              }
              className="flex w-full items-center gap-2 border-b border-black bg-paper-tint px-3 py-1 text-left font-mono text-xs tracking-wider text-steel-grey uppercase"
            >
              {isExpanded
                ? t('diff.hideUnchangedRows', { count: chunk.rows.length })
                : t('diff.showUnchangedRows', { count: chunk.rows.length })}
            </button>
            {isExpanded && body}
          </div>
        );
      })}
    </div>
  );
}

export interface DiffModeToggleProps {
  view: DiffViewMode;
  onChange: (view: DiffViewMode) => void;
}

/** Unified/split switch. Snaps between states — no transition. */
export function DiffModeToggle({ view, onChange }: DiffModeToggleProps) {
  const { t } = useTranslations();
  return (
    <div className="flex border-2 border-black">
      <button
        type="button"
        aria-pressed={view === 'unified'}
        onClick={() => onChange('unified')}
        className={`border-r-2 border-black px-3 py-1 font-mono text-xs tracking-wider uppercase ${
          view === 'unified' ? 'bg-black text-white' : 'bg-white text-ink'
        }`}
      >
        {t('diff.view.unified')}
      </button>
      <button
        type="button"
        aria-pressed={view === 'split'}
        onClick={() => onChange('split')}
        className={`px-3 py-1 font-mono text-xs tracking-wider uppercase ${
          view === 'split' ? 'bg-black text-white' : 'bg-white text-ink'
        }`}
      >
        {t('diff.view.split')}
      </button>
    </div>
  );
}

export interface DiffViewProps {
  diff: DocumentDiff;
  initialView?: DiffViewMode;
  /** Accepted row paths. Required when `onAcceptedPathsChange` is supplied. */
  acceptedPaths?: readonly string[];
  /**
   * Supplying this turns the surface into a partial-accept picker: every
   * selectable row gets a checkbox and each change reports the full selection.
   */
  onAcceptedPathsChange?: (paths: string[]) => void;
}

/**
 * The one diff surface: stats, a unified/split toggle and section groups.
 *
 * Group state comes from the response — sections are user-named, so nothing
 * here can be seeded from a fixed list of section keys.
 */
export function DiffView({
  diff,
  initialView = 'unified',
  acceptedPaths,
  onAcceptedPathsChange,
}: DiffViewProps) {
  const { t } = useTranslations();
  const [view, setView] = useState<DiffViewMode>(initialView);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  const selectable = useMemo(() => selectablePaths(diff), [diff]);
  const selected = useMemo(() => new Set(acceptedPaths ?? []), [acceptedPaths]);

  // Seeded from the response: a section that changed opens, a fully unchanged
  // one stays shut.
  const defaultExpanded = useMemo(() => {
    const seed: Record<string, boolean> = {
      header: diff.header.some((row) => row.status !== 'unchanged'),
    };
    diff.sections.forEach((section, index) => {
      seed[`${index}:${section.head_key ?? section.base_key ?? ''}`] =
        section.status !== 'unchanged' || section.rows.some((row) => row.status !== 'unchanged');
    });
    return seed;
  }, [diff]);

  useEffect(() => {
    setExpandedGroups(defaultExpanded);
  }, [defaultExpanded]);

  const emit = (next: Set<string>) => {
    onAcceptedPathsChange?.(selectable.filter((path) => next.has(path)));
  };

  const togglePath = (path: string, isOn: boolean) => {
    const next = new Set(selected);
    if (isOn) next.add(path);
    else next.delete(path);
    emit(next);
  };

  const toggleGroup = (key: string) => {
    setExpandedGroups((current) => ({ ...current, [key]: !(current[key] ?? false) }));
  };

  const headerStatus = diff.header.some((row) => row.status !== 'unchanged')
    ? 'modified'
    : 'unchanged';

  return (
    <div className="space-y-4">
      <DiffStatsBar stats={diff.stats} />

      <div className="flex flex-wrap items-center justify-between gap-4">
        <DiffModeToggle view={view} onChange={setView} />

        {onAcceptedPathsChange && (
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs tracking-wider text-steel-grey uppercase">
              {t('diff.selectedCount', { count: selected.size, total: selectable.length })}
            </span>
            <Button variant="outline" size="sm" onClick={() => emit(new Set(selectable))}>
              {t('diff.selectAll')}
            </Button>
            <Button variant="outline" size="sm" onClick={() => emit(new Set())}>
              {t('diff.clearAll')}
            </Button>
          </div>
        )}
      </div>

      {view === 'split' && (
        // Mirrors a row's gutter so the labels sit over their own columns.
        <div className="flex gap-2 border-2 border-black bg-white px-3 py-1">
          <span aria-hidden="true" className="w-4 shrink-0" />
          <div className="flex min-w-0 flex-1">
            <span className="w-1/2 border-r-2 border-black pr-3 font-mono text-xs tracking-wider text-steel-grey uppercase">
              {t('diff.baseLabel')}
            </span>
            <span className="w-1/2 pl-3 font-mono text-xs tracking-wider text-steel-grey uppercase">
              {t('diff.headLabel')}
            </span>
          </div>
        </div>
      )}

      {diff.header.length > 0 && (
        <DiffSectionGroup
          status={headerStatus}
          baseHeading={null}
          headHeading={t('diff.headerSection')}
          rowCount={diff.header.length}
          isExpanded={expandedGroups.header ?? false}
          onToggle={() => toggleGroup('header')}
        >
          <DiffRows
            rows={diff.header}
            view={view}
            selectedPaths={selected}
            onTogglePath={onAcceptedPathsChange ? togglePath : undefined}
          />
        </DiffSectionGroup>
      )}

      {diff.sections.map((section, index) => {
        const key = `${index}:${section.head_key ?? section.base_key ?? ''}`;
        return (
          <DiffSectionGroup
            key={key}
            status={section.status}
            baseHeading={section.base_heading ?? section.base_key}
            headHeading={section.head_heading ?? section.head_key}
            rowCount={section.rows.length}
            isExpanded={expandedGroups[key] ?? false}
            onToggle={() => toggleGroup(key)}
          >
            <DiffRows
              rows={section.rows}
              view={view}
              selectedPaths={selected}
              onTogglePath={onAcceptedPathsChange ? togglePath : undefined}
            />
          </DiffSectionGroup>
        );
      })}
    </div>
  );
}

export default DiffView;
