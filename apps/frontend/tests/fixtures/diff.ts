/**
 * `DocumentDiff` fixtures.
 *
 * The shapes mirror `app/schemas/diff.py`; tests that need "a diff with these
 * rows" build one here rather than repeating the envelope.
 */

import type { DiffRow, DiffStats, DocumentDiff, SectionDiff } from '@/lib/api/diff';

export function makeStats(overrides: Partial<DiffStats> = {}): DiffStats {
  return {
    sections_added: 0,
    sections_removed: 0,
    sections_renamed: 0,
    sections_moved: 0,
    entries_added: 0,
    entries_removed: 0,
    entries_modified: 0,
    entries_moved: 0,
    bullets_added: 0,
    bullets_removed: 0,
    bullets_modified: 0,
    tags_added: 0,
    tags_removed: 0,
    total_changes: 0,
    ...overrides,
  };
}

export function makeRow(overrides: Partial<DiffRow> = {}): DiffRow {
  return {
    kind: 'bullet',
    status: 'unchanged',
    path: 'sections.experience.entries[0].bullets[0].text',
    base_text: null,
    head_text: null,
    spans: [],
    anchor: {},
    ...overrides,
  };
}

export function makeSectionDiff(overrides: Partial<SectionDiff> = {}): SectionDiff {
  return {
    status: 'modified',
    base_key: 'experience',
    head_key: 'experience',
    base_heading: 'Experience',
    head_heading: 'Experience',
    base_index: 0,
    head_index: 0,
    rows: [],
    ...overrides,
  };
}

export function makeDocumentDiff(overrides: Partial<DocumentDiff> = {}): DocumentDiff {
  return {
    stats: makeStats(),
    header: [],
    sections: [],
    ...overrides,
  };
}
