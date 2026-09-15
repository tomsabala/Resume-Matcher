import { describe, expect, it } from 'vitest';

import type { ResumeDocument, Section } from '@/lib/types/document';
import {
  buildResumeDraft,
  getResumeDraftStorageKey,
  parseResumeDraft,
  RESUME_DRAFT_MAX_AGE_MS,
  RESUME_DRAFT_MAX_CLOCK_SKEW_MS,
  isResumeDocumentShape,
  isSameResumeDocument,
  shouldPromptForDraftRestore,
} from '@/lib/utils/resume-draft-storage';

function section(overrides: Partial<Section> = {}): Section {
  return {
    id: 'sec-1',
    key: 'summary',
    heading: 'Summary',
    headingI18nKey: null,
    kind: 'text',
    visible: true,
    column: 'main',
    text: '',
    entries: [],
    tags: [],
    groups: [],
    ...overrides,
  };
}

const baseResume: ResumeDocument = {
  schemaVersion: 2,
  header: {
    name: 'Ada Lovelace',
    headline: 'Software Engineer',
    contacts: [{ id: 'c-1', kind: 'email', label: 'Email', value: 'ada@example.com', url: '' }],
  },
  sections: [section()],
};

describe('resume draft storage helpers', () => {
  it('scopes saved drafts by resume id', () => {
    expect(getResumeDraftStorageKey('abc-123')).toBe('resume_builder_draft:abc-123');
    expect(getResumeDraftStorageKey(null)).toBe('resume_builder_draft:new');
  });

  it('wraps draft data with identity and timestamp metadata', () => {
    expect(buildResumeDraft('abc-123', baseResume, 1770000000000)).toEqual({
      resumeId: 'abc-123',
      updatedAt: 1770000000000,
      data: baseResume,
    });
  });

  it('parses both the new draft envelope and the legacy plain data shape', () => {
    // Timestamp must be recent: drafts past RESUME_DRAFT_MAX_AGE_MS are expired
    // by design (see the "draft expiry" suite below). This case is about the
    // round-trip shape, not the TTL.
    const envelope = buildResumeDraft('abc-123', baseResume, Date.now() - 1000);
    expect(parseResumeDraft(JSON.stringify(envelope), 'abc-123')).toEqual(envelope);

    expect(parseResumeDraft(JSON.stringify(baseResume), 'abc-123', 1770000000100)).toEqual({
      resumeId: 'abc-123',
      updatedAt: 1770000000100,
      data: baseResume,
    });
  });

  it('rejects a pre-migration draft instead of restoring a dead shape', () => {
    // A v1 draft in localStorage carries the six-section shape. Restoring it
    // would replace a migrated server document with fields nothing renders.
    const legacyDraft = {
      personalInfo: { name: 'Ada Lovelace' },
      summary: 'Engineer',
      workExperience: [],
    };
    expect(isResumeDocumentShape(legacyDraft)).toBe(false);
    expect(parseResumeDraft(JSON.stringify(legacyDraft), 'abc-123')).toBeNull();
    expect(
      parseResumeDraft(
        JSON.stringify({ resumeId: 'abc-123', updatedAt: Date.now(), data: legacyDraft }),
        'abc-123'
      )
    ).toBeNull();
  });

  it('rejects malformed JSON without throwing', () => {
    // T-02: every input in the "valid JSON" case below parses cleanly, so the
    // try/catch in parseResumeDraft was never exercised — it could be deleted
    // outright and this suite stayed green. These hit the catch.
    expect(parseResumeDraft('{oops', 'abc-123')).toBeNull();
    expect(parseResumeDraft('{"data": {', 'abc-123')).toBeNull();
    expect(parseResumeDraft('undefined', 'abc-123')).toBeNull();
  });

  it('rejects valid JSON that does not look like a resume document', () => {
    expect(parseResumeDraft('"not a resume"', 'abc-123')).toBeNull();
    expect(parseResumeDraft(JSON.stringify({ data: 42, updatedAt: 1 }), 'abc-123')).toBeNull();
    expect(parseResumeDraft(JSON.stringify({ ...baseResume, sections: {} }), 'abc-123')).toBeNull();
  });

  it('rejects an envelope for a different resume id', () => {
    const otherResumeDraft = buildResumeDraft('other-resume', baseResume, 1770000000000);

    expect(parseResumeDraft(JSON.stringify(otherResumeDraft), 'abc-123')).toBeNull();
  });

  it('can reject legacy plain drafts when they cannot be safely scoped', () => {
    expect(
      parseResumeDraft(JSON.stringify(baseResume), 'abc-123', 1770000000100, {
        allowLegacyPlainData: false,
      })
    ).toBeNull();
  });

  it('only prompts restore when the draft differs from the server copy', () => {
    expect(shouldPromptForDraftRestore(buildResumeDraft('abc-123', baseResume), baseResume)).toBe(
      false
    );

    const changedDraft = buildResumeDraft('abc-123', {
      ...baseResume,
      sections: [...baseResume.sections, section({ id: 'sec-2', key: 'skills', kind: 'tags' })],
    });

    expect(shouldPromptForDraftRestore(changedDraft, baseResume)).toBe(true);
  });
});

describe('draft expiry', () => {
  it('rejects a draft older than the max age', () => {
    const stale = JSON.stringify({
      resumeId: 'abc-123',
      updatedAt: Date.now() - (RESUME_DRAFT_MAX_AGE_MS + 60_000),
      data: baseResume,
    });

    expect(parseResumeDraft(stale, 'abc-123')).toBeNull();
  });

  it('keeps a draft inside the max age', () => {
    const fresh = JSON.stringify({
      resumeId: 'abc-123',
      updatedAt: Date.now() - (RESUME_DRAFT_MAX_AGE_MS - 60_000),
      data: baseResume,
    });

    expect(parseResumeDraft(fresh, 'abc-123')).not.toBeNull();
  });
});

describe('draft expiry determinism', () => {
  it('evaluates age against a supplied `now` instead of the wall clock', () => {
    const writtenAt = 1_770_000_000_000;
    const draft = JSON.stringify({ resumeId: 'abc-123', updatedAt: writtenAt, data: baseResume });

    // Just inside the window relative to the supplied clock.
    expect(
      parseResumeDraft(draft, 'abc-123', undefined, {
        now: writtenAt + RESUME_DRAFT_MAX_AGE_MS - 1,
      })
    ).not.toBeNull();

    // Just outside it.
    expect(
      parseResumeDraft(draft, 'abc-123', undefined, {
        now: writtenAt + RESUME_DRAFT_MAX_AGE_MS + 1,
      })
    ).toBeNull();
  });
});

describe('isSameResumeDocument structural comparison', () => {
  it('treats reordered object keys as equal', () => {
    // A client-authored draft and a Pydantic-serialised server response can
    // carry identical data in a different key order. JSON.stringify equality
    // called that "unsaved work" and popped a recovery dialog whose two
    // options were indistinguishable.
    const left = { ...baseResume, header: { ...baseResume.header, name: 'Ada', headline: 'Eng' } };
    const right = {
      ...baseResume,
      header: { headline: 'Eng', name: 'Ada', contacts: baseResume.header.contacts },
    };

    expect(isSameResumeDocument(left, right)).toBe(true);
    expect(shouldPromptForDraftRestore(buildResumeDraft('abc-123', left), right)).toBe(false);
  });

  it('still reports a real difference', () => {
    const left = { ...baseResume, sections: [section({ text: 'one' })] };
    const right = { ...baseResume, sections: [section({ text: 'two' })] };

    expect(isSameResumeDocument(left, right)).toBe(false);
  });

  it('keeps section order significant', () => {
    const skills = section({ id: 'sec-2', key: 'skills', kind: 'tags', tags: ['a'] });
    const left = { ...baseResume, sections: [section(), skills] };
    const right = { ...baseResume, sections: [skills, section()] };

    expect(isSameResumeDocument(left, right)).toBe(false);
  });
});

describe('draft clock skew', () => {
  it('rejects a draft stamped far in the future', () => {
    const now = 1_800_000_000_000;
    const future = JSON.stringify({
      resumeId: 'abc-123',
      updatedAt: now + RESUME_DRAFT_MAX_CLOCK_SKEW_MS + 60_000,
      data: baseResume,
    });

    expect(parseResumeDraft(future, 'abc-123', undefined, { now })).toBeNull();
  });

  it('tolerates small skew', () => {
    const now = 1_800_000_000_000;
    const slightlyAhead = JSON.stringify({
      resumeId: 'abc-123',
      updatedAt: now + 60_000,
      data: baseResume,
    });

    expect(parseResumeDraft(slightlyAhead, 'abc-123', undefined, { now })).not.toBeNull();
  });
});

describe('draft timestamp validation', () => {
  it('rejects a non-finite timestamp', () => {
    // JSON.parse cannot produce NaN (it throws on the literal), but it DOES
    // produce Infinity for an overflowing numeric literal. Both the TTL and
    // skew comparisons already reject those; Number.isFinite in the shape
    // check makes the invariant explicit rather than incidental.
    const overflow = `{"resumeId":"abc-123","updatedAt":1e400,"data":${JSON.stringify(baseResume)}}`;
    expect(parseResumeDraft(overflow, 'abc-123')).toBeNull();

    const negOverflow = `{"resumeId":"abc-123","updatedAt":-1e400,"data":${JSON.stringify(baseResume)}}`;
    expect(parseResumeDraft(negOverflow, 'abc-123')).toBeNull();
  });

  it('rejects a non-numeric timestamp', () => {
    const stringy = `{"resumeId":"abc-123","updatedAt":"yesterday","data":${JSON.stringify(baseResume)}}`;
    expect(parseResumeDraft(stringy, 'abc-123')).toBeNull();
  });
});
