/**
 * Which diff rows a user can accept individually.
 *
 * Mirrors `document_diff.merge_accepted`: only content leaves can be taken from
 * a proposal, because structural rows (an entry header, a group label) have no
 * independent meaning once their leaves are decided.
 */

import type { DocumentDiff, DiffRow } from '@/lib/api/diff';

const SELECTABLE_PATHS: RegExp[] = [
  /^sections\.[^[\]]+\.text$/,
  /^sections\.[^[\]]+\.tags$/,
  /^sections\..+\.groups\[\d+\]\.values$/,
  /^sections\..+\.entries\[\d+\]\.summary$/,
  /^sections\..+\.entries\[\d+\]\.bullets\[\d+\]\.text$/,
];

/**
 * True when this row can carry an accept/reject checkbox: a changed content
 * leaf the confirm endpoint knows how to take on its own.
 */
export function isSelectableRow(row: DiffRow): boolean {
  if (row.status === 'unchanged') return false;
  return SELECTABLE_PATHS.some((pattern) => pattern.test(row.path));
}

/**
 * Every distinct selectable path in the diff, in row order.
 *
 * A tag list and a group's values produce one row per value but share a single
 * path, so the result is deduplicated: accepting that path takes the whole list.
 */
export function selectablePaths(diff: DocumentDiff): string[] {
  const seen = new Set<string>();
  const paths: string[] = [];
  const collect = (rows: DiffRow[]) => {
    for (const row of rows) {
      if (!isSelectableRow(row) || seen.has(row.path)) continue;
      seen.add(row.path);
      paths.push(row.path);
    }
  };
  collect(diff.header);
  for (const section of diff.sections) collect(section.rows);
  return paths;
}
