'use client';

import React from 'react';
import { useTranslations } from '@/lib/i18n';
import type { DiffRow, DiffSpan, RowStatus } from '@/lib/api/diff';
import { isSelectableRow } from './paths';

/**
 * Status is a left rule, never a tinted background: the row keeps the white
 * paper it is printed on, and the rule carries the state at the margin.
 */
export const ROW_RULE_CLASS: Record<RowStatus, string> = {
  added: 'border-l-4 border-green-700',
  removed: 'border-l-4 border-red-600',
  modified: 'border-l-4 border-orange-500',
  moved: 'border-l-4 border-blue-700',
  unchanged: 'border-l-4 border-transparent',
};

const GUTTER_GLYPH: Record<RowStatus, string> = {
  added: '+',
  removed: '\u2212',
  modified: '~',
  moved: '\u00bb',
  unchanged: '\u00b7',
};

const SPAN_CLASS: Record<'base' | 'head', string> = {
  base: 'bg-red-600 text-white',
  head: 'bg-green-700 text-white',
};

interface SpannedTextProps {
  text: string;
  spans: DiffSpan[];
  side: 'base' | 'head';
}

/**
 * Text with the server's character ranges marked.
 *
 * Offsets come from the diff engine; ranges are clamped and skipped when they
 * overlap so a stale or malformed span can never drop characters.
 */
function SpannedText({ text, spans, side }: SpannedTextProps) {
  const marks = spans
    .filter((span) => span.side === side)
    .map((span) => ({
      start: Math.max(0, Math.min(span.start, text.length)),
      end: Math.max(0, Math.min(span.end, text.length)),
    }))
    .filter((span) => span.end > span.start)
    .sort((left, right) => left.start - right.start);

  if (marks.length === 0) return <>{text}</>;

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  marks.forEach((span, index) => {
    if (span.start < cursor) return;
    if (span.start > cursor) parts.push(text.slice(cursor, span.start));
    parts.push(
      <mark key={`${side}-${index}`} className={`${SPAN_CLASS[side]} px-0.5`}>
        {text.slice(span.start, span.end)}
      </mark>
    );
    cursor = span.end;
  });
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}

interface SideTextProps {
  row: DiffRow;
  side: 'base' | 'head';
}

function SideText({ row, side }: SideTextProps) {
  const text = (side === 'base' ? row.base_text : row.head_text) ?? '';
  if (!text) return null;
  return <SpannedText text={text} spans={row.spans} side={side} />;
}

export interface DiffRowLineProps {
  row: DiffRow;
  view: 'unified' | 'split';
  /** Present only when the caller collects accepted paths. */
  checked?: boolean;
  onToggle?: (path: string, next: boolean) => void;
}

/**
 * One diff row: gutter, left status rule, and the text of one or both sides.
 *
 * Unified shows a modified row as its base line above its head line; split puts
 * base left of the black divider and head right of it.
 */
export function DiffRowLine({ row, view, checked, onToggle }: DiffRowLineProps) {
  const { t } = useTranslations();
  const showCheckbox = onToggle !== undefined && isSelectableRow(row);

  const content =
    view === 'split' ? (
      <div className="flex h-full max-sm:flex-col">
        <div className="w-1/2 border-r-2 border-black pr-3 max-sm:w-full max-sm:border-r-0 max-sm:border-b-2 max-sm:pr-0 max-sm:pb-1">
          <SideText row={row} side="base" />
        </div>
        <div className="w-1/2 pl-3 max-sm:w-full max-sm:pl-0 max-sm:pt-1">
          <SideText row={row} side="head" />
        </div>
      </div>
    ) : row.status === 'modified' ? (
      <>
        <div className="flex gap-2">
          <span aria-hidden="true" className="w-3 shrink-0 text-steel-grey">
            {GUTTER_GLYPH.removed}
          </span>
          <span className="min-w-0 flex-1">
            <SideText row={row} side="base" />
          </span>
        </div>
        <div className="flex gap-2">
          <span aria-hidden="true" className="w-3 shrink-0 text-steel-grey">
            {GUTTER_GLYPH.added}
          </span>
          <span className="min-w-0 flex-1">
            <SideText row={row} side="head" />
          </span>
        </div>
      </>
    ) : (
      <SideText row={row} side={row.status === 'removed' ? 'base' : 'head'} />
    );

  return (
    <div
      data-status={row.status}
      data-path={row.path}
      className={`flex items-start gap-2 border-b border-black bg-white px-3 py-1 ${ROW_RULE_CLASS[row.status]}`}
    >
      {showCheckbox && (
        <input
          type="checkbox"
          checked={checked ?? false}
          onChange={(event) => onToggle?.(row.path, event.target.checked)}
          aria-label={t('diff.acceptRow', { path: row.path })}
          className="relative mt-1 h-3 w-3 shrink-0 cursor-pointer appearance-none border border-black bg-white before:absolute before:-inset-[16px] before:content-[''] checked:bg-black"
        />
      )}
      <span
        aria-hidden="true"
        className="w-4 shrink-0 select-none font-mono text-xs leading-5 text-steel-grey"
      >
        {GUTTER_GLYPH[row.status]}
      </span>
      <span className="sr-only">{t(`diff.status.${row.status}`)}</span>
      <div className="min-w-0 flex-1 font-mono text-xs leading-5 break-words whitespace-pre-wrap">
        {content}
      </div>
    </div>
  );
}

export default DiffRowLine;
